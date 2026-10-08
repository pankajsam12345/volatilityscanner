"""
Configurable fair-value models (§20). Two deliberately simple, swappable
models rather than one hard-coded universal formula:

  - "historical_mean": fair value = the metric's own trailing history mean
    (a mean-reversion assumption). This is the default for skew/RR/BF/
    calendar/forward-vol, since a principled structural model for each is
    genuinely underdetermined without more market data than a demo app has.

  - "regression": fair IV = intercept + slope * RV, fit by OLS over trailing
    (RV, IV) pairs. Used for the IV/RV relationship, where a linear
    volatility-risk-premium regression is a standard, defensible starting
    model. Falls back to historical_mean if there isn't enough history to
    fit a stable regression.

Both return None (not a number) when there isn't enough history — callers
must treat "no fair value available" as a real state, not silently trade
on an unfounded number.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def historical_mean_fair_value(history: list[float]) -> float | None:
    clean = [h for h in history if h is not None]
    if len(clean) < 5:
        return None
    return float(np.mean(clean))


@dataclass(frozen=True)
class RegressionFairValue:
    fair_value: float
    slope: float
    intercept: float
    r_squared: float
    sample_size: int


def iv_rv_regression_fair_value(
    rv_history: list[float], iv_history: list[float], current_rv: float, min_samples: int = 20,
) -> RegressionFairValue | None:
    pairs = [(rv, iv) for rv, iv in zip(rv_history, iv_history) if rv is not None and iv is not None]
    if len(pairs) < min_samples:
        return None
    rv_arr = np.array([p[0] for p in pairs])
    iv_arr = np.array([p[1] for p in pairs])
    if rv_arr.std() < 1e-9:
        return None

    slope, intercept = np.polyfit(rv_arr, iv_arr, 1)
    predicted = slope * rv_arr + intercept
    ss_res = float(np.sum((iv_arr - predicted) ** 2))
    ss_tot = float(np.sum((iv_arr - iv_arr.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

    fair_iv = slope * current_rv + intercept
    return RegressionFairValue(float(fair_iv), float(slope), float(intercept), float(r_squared), len(pairs))


def iv_rv_fair_spread(
    rv_history: list[float], iv_history: list[float], current_rv: float, min_samples: int = 20,
) -> tuple[float | None, str]:
    """Returns (fair IV-RV spread, model used)."""
    reg = iv_rv_regression_fair_value(rv_history, iv_history, current_rv, min_samples)
    if reg is not None and reg.r_squared > 0.1:
        return reg.fair_value - current_rv, "regression"
    spread_history = [
        iv - rv for rv, iv in zip(rv_history, iv_history) if rv is not None and iv is not None
    ]
    mean_spread = historical_mean_fair_value(spread_history)
    return mean_spread, "historical_mean"
