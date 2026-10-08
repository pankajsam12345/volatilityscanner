"""
Transparent, component-based opportunity scoring (§24). The final score is
a disclosed weighted sum of six named components — never an opaque number.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreBreakdown:
    statistical_edge: float
    historical_consistency: float
    liquidity: float
    cost_efficiency: float
    model_confidence: float
    risk: float
    total: float
    weights: dict

    def as_dict(self) -> dict:
        return {
            "statistical_edge": round(self.statistical_edge, 1),
            "historical_consistency": round(self.historical_consistency, 1),
            "liquidity": round(self.liquidity, 1),
            "cost_efficiency": round(self.cost_efficiency, 1),
            "model_confidence": round(self.model_confidence, 1),
            "risk": round(self.risk, 1),
            "total": round(self.total, 1),
            "weights": self.weights,
        }


def statistical_edge_score(zscore: float | None, cap: float = 3.0) -> float:
    if zscore is None:
        return 0.0
    return float(min(abs(zscore) / cap, 1.0) * 100)


def historical_consistency_score(percentile: float | None) -> float:
    """Distance of the percentile from the 50th percentile (a neutral/unremarkable reading)."""
    if percentile is None:
        return 0.0
    return float(min(abs(percentile - 50) / 50, 1.0) * 100)


def cost_efficiency_score(net_edge: float, gross_edge: float) -> float:
    if gross_edge is None or gross_edge <= 0:
        return 0.0
    return float(max(0.0, min(net_edge / gross_edge, 1.0)) * 100)


def model_confidence_score(sample_size: int, no_arb_flags_failed: int, data_quality: str, target_sample: int) -> float:
    """
    target_sample should be the full configured historical lookback
    (settings.percentile_lookback_days), not an arbitrary "enough data"
    floor — a fixed low floor (this used a hard-coded 120 before) saturates
    to 100 for every opportunity once the seeded history is deep enough to
    clear it, which stops discriminating between opportunities entirely.
    Scoring against the actual target instead means an opportunity built on
    a metric's *full* configured window scores 100, while one whose history
    is shorter for a real reason (e.g. calendar-pair validity filtering,
    fewer solvable historical days for that specific bucket) scores
    proportionally lower — a real, varying signal again.
    """
    base = min(sample_size / target_sample, 1.0) * 100
    base -= no_arb_flags_failed * 15
    if data_quality != "GOOD":
        base -= 20
    return float(max(0.0, min(base, 100.0)))


def risk_score(max_risk_normalized: float) -> float:
    """max_risk_normalized in [0, 1]: fraction of a configured risk budget consumed. Lower risk -> higher score."""
    return float(max(0.0, min(1.0 - max_risk_normalized, 1.0)) * 100)


def score_opportunity(
    statistical_edge: float, historical_consistency: float, liquidity: float,
    cost_efficiency: float, model_confidence: float, risk: float, weights: dict,
) -> ScoreBreakdown:
    total = (
        weights["statistical_edge"] * statistical_edge
        + weights["historical_consistency"] * historical_consistency
        + weights["liquidity"] * liquidity
        + weights["cost_efficiency"] * cost_efficiency
        + weights["model_confidence"] * model_confidence
        + weights["risk"] * risk
    )
    return ScoreBreakdown(
        statistical_edge=statistical_edge, historical_consistency=historical_consistency,
        liquidity=liquidity, cost_efficiency=cost_efficiency, model_confidence=model_confidence,
        risk=risk, total=total, weights=weights,
    )
