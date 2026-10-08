"""
Volatility regime detection (§38): classifies LOW/NORMAL/HIGH/EXTREME from
RV20's own historical percentile — reuses the same distribution_context
used everywhere else in the app, so "regime" is just another view onto the
identical historical-percentile engine, not a separate ad-hoc model.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.stats import DistributionContext, distribution_context


@dataclass(frozen=True)
class RegimeResult:
    regime: str  # LOW | NORMAL | HIGH | EXTREME | UNKNOWN
    current: float
    percentile: float | None
    zscore: float | None
    history: DistributionContext | None


def classify_regime(
    current_rv: float, rv_history: list[float],
    low_percentile: float = 25.0, high_percentile: float = 75.0, extreme_percentile: float = 95.0,
) -> RegimeResult:
    ctx = distribution_context(current_rv, rv_history)
    if ctx is None:
        return RegimeResult("UNKNOWN", current_rv, None, None, None)

    p = ctx.percentile
    if p >= extreme_percentile:
        regime = "EXTREME"
    elif p >= high_percentile:
        regime = "HIGH"
    elif p >= low_percentile:
        regime = "NORMAL"
    else:
        regime = "LOW"

    return RegimeResult(regime, current_rv, p, ctx.zscore, ctx)
