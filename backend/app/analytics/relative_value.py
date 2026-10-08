"""
Generic relative-value evaluation (§19): every "current vs fair, vs history"
relationship in the app — IV vs RV, front IV vs back IV, current skew vs
historical skew, current RR/BF vs historical RR/BF, calendar spread vs
historical calendar spread, forward vol vs spot vol — reduces to the same
five numbers: Observed, Fair Value, Deviation, Z-score, Percentile, and a
Signal. This module computes that tuple once, generically, so every
opportunity type in opportunities/strategies.py builds on the same logic.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.stats import DistributionContext, distribution_context


@dataclass(frozen=True)
class RelativeValueSignal:
    metric_name: str
    observed: float
    fair_value: float | None
    fair_value_model: str | None
    deviation: float | None  # observed - fair_value
    history: DistributionContext | None
    signal: str  # "RICH" | "CHEAP" | "NEUTRAL" | "INSUFFICIENT_DATA"
    strength: float  # 0..1, saturates at 2x the z-score threshold


def evaluate_relative_value(
    metric_name: str,
    observed: float,
    history_series: list[float],
    fair_value: float | None = None,
    fair_value_model: str | None = None,
    zscore_threshold: float = 2.0,
) -> RelativeValueSignal:
    ctx = distribution_context(observed, history_series)
    deviation = (observed - fair_value) if fair_value is not None else None

    if ctx is None:
        return RelativeValueSignal(
            metric_name, observed, fair_value, fair_value_model, deviation,
            None, "INSUFFICIENT_DATA", 0.0,
        )

    z = ctx.zscore
    if z >= zscore_threshold:
        signal = "RICH"
    elif z <= -zscore_threshold:
        signal = "CHEAP"
    else:
        signal = "NEUTRAL"

    strength = min(abs(z) / (zscore_threshold * 2), 1.0) if zscore_threshold > 0 else 0.0

    return RelativeValueSignal(metric_name, observed, fair_value, fair_value_model, deviation, ctx, signal, strength)
