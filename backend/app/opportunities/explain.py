"""
Explainability (§25/§43). Every opportunity must answer: why was this
detected, what's the historical relationship, what's the deviation/edge,
what does it cost, what could make it fail, what's the main risk.
"""
from __future__ import annotations

from app.analytics.relative_value import RelativeValueSignal
from app.costs.transaction_cost import StrategyCost

GENERIC_RISKS = [
    "IV regime change",
    "Spot gap risk",
    "Volatility term-structure shift",
    "Liquidity deterioration",
    "Model error / smile misspecification",
]

STRATEGY_RISKS = {
    "IV_RV": ["Realized volatility spikes above the level implied by the historical IV-RV relationship", "Earnings/event risk not reflected in the trailing RV window"],
    "CALENDAR": ["Near-term event risk (earnings, data release) concentrated in one leg", "Front-tenor vol can decouple from back-tenor vol around expiry"],
    "RISK_REVERSAL": ["A sharp directional move can make the skew look 'fair' in hindsight while the position loses on delta", "Skew regimes can persist longer than the historical window suggests"],
    "BUTTERFLY": ["Realized jump risk not captured by the historical butterfly distribution", "Wide bid/ask on wing strikes can erode the edge faster than modeled"],
    "SKEW": ["Downside realized volatility can catch up to the elevated put skew", "Skew can stay rich/cheap through an entire regime"],
    "FORWARD_VOL": ["Forward vol is a model construct, not a tradeable instrument on its own — realizing the edge requires a calendar structure with its own risks"],
}


def build_why(signal: RelativeValueSignal, extra_context: list[str] | None = None) -> list[str]:
    why: list[str] = []
    if signal.history is not None:
        why.append(
            f"{signal.metric_name} is {signal.history.zscore:+.2f} standard deviations from its "
            f"{signal.history.sample_size}-observation historical mean ({signal.history.mean:.4f}), "
            f"at the {signal.history.percentile:.0f}th percentile."
        )
    if signal.fair_value is not None and signal.deviation is not None:
        why.append(
            f"Fair-value model ({signal.fair_value_model}) estimates {signal.fair_value:.4f}; "
            f"observed value deviates by {signal.deviation:+.4f}."
        )
    if extra_context:
        why.extend(extra_context)
    return why


def build_risks(strategy_key: str, extra: list[str] | None = None) -> list[str]:
    risks = list(STRATEGY_RISKS.get(strategy_key, [])) + GENERIC_RISKS
    if extra:
        risks = list(extra) + risks
    return risks


def build_cost_note(cost: StrategyCost) -> str:
    return (
        f"Gross edge {cost.gross_edge:+.2f} vol pts, transaction+hedging cost "
        f"{cost.breakeven_cost:.2f} vol pts -> net edge {cost.net_edge:+.2f} vol pts."
    )
