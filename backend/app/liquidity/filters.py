"""Liquidity filter (§23): every leg and every opportunity gets an explicit HIGH/MEDIUM/LOW/REJECTED status."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LiquidityAssessment:
    status: str  # HIGH | MEDIUM | LOW | REJECTED
    spread_pct: float | None
    reasons: list[str] = field(default_factory=list)


def assess_leg_liquidity(
    bid: float, ask: float, volume: int, open_interest: int, settings
) -> LiquidityAssessment:
    reasons: list[str] = []
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return LiquidityAssessment("REJECTED", None, ["Invalid or crossed bid/ask"])

    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100 if mid > 0 else 100.0

    if open_interest < settings.min_open_interest:
        reasons.append(f"OI {open_interest} below minimum {settings.min_open_interest}")
    if volume < settings.min_volume:
        reasons.append(f"Volume {volume} below minimum {settings.min_volume}")
    if spread_pct > settings.max_bid_ask_spread_pct:
        reasons.append(f"Spread {spread_pct:.1f}% above maximum {settings.max_bid_ask_spread_pct:.1f}%")
    if reasons:
        return LiquidityAssessment("REJECTED", spread_pct, reasons)

    if (
        open_interest >= settings.high_liquidity_oi
        and volume >= settings.high_liquidity_volume
        and spread_pct <= settings.high_liquidity_spread_pct
    ):
        return LiquidityAssessment("HIGH", spread_pct)
    if (
        open_interest >= settings.medium_liquidity_oi
        and volume >= settings.medium_liquidity_volume
        and spread_pct <= settings.medium_liquidity_spread_pct
    ):
        return LiquidityAssessment("MEDIUM", spread_pct)
    return LiquidityAssessment("LOW", spread_pct)


_RANK = {"REJECTED": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def aggregate_liquidity(statuses: list[str]) -> str:
    """Overall liquidity is only as good as its weakest leg."""
    if not statuses:
        return "REJECTED"
    worst = min(statuses, key=lambda s: _RANK.get(s, 0))
    return worst


def liquidity_score(status: str) -> float:
    return {"HIGH": 100.0, "MEDIUM": 65.0, "LOW": 35.0, "REJECTED": 0.0}.get(status, 0.0)
