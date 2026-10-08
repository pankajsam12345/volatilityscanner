"""
No-arbitrage / market-quality validation (§53).

These produce FLAGS, not trade signals. Per spec: "Flag questionable
opportunities rather than automatically trading them" and "Do NOT label
something as risk-free arbitrage unless mathematical arbitrage conditions
are actually satisfied."
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.black_scholes import put_call_parity_deviation
from app.analytics.term_structure import ForwardVolResult


@dataclass(frozen=True)
class NoArbFlag:
    check: str
    passed: bool
    detail: str


def check_put_call_parity(
    call_price: float, put_price: float, spot: float, strike: float,
    t: float, r: float, q: float = 0.0, tolerance_pct_of_spot: float = 0.5,
) -> NoArbFlag:
    deviation = put_call_parity_deviation(call_price, put_price, spot, strike, t, r, q)
    tolerance = spot * tolerance_pct_of_spot / 100
    passed = abs(deviation) <= tolerance
    return NoArbFlag(
        check="PUT_CALL_PARITY",
        passed=passed,
        detail=f"C-P vs S*e^-qT-K*e^-rT deviation = {deviation:.4f} (tolerance {tolerance:.4f})",
    )


def check_calendar_variance(fv: ForwardVolResult, near_label: str, far_label: str) -> NoArbFlag:
    return NoArbFlag(
        check="CALENDAR_VARIANCE_CONSISTENCY",
        passed=fv.valid,
        detail=(
            f"{near_label}->{far_label} forward variance is "
            f"{'valid' if fv.valid else 'NEGATIVE (' + (fv.error or '') + ')'}"
        ),
    )


def check_butterfly_convexity(bf_value: float | None, delta_label: str, tolerance: float = -0.005) -> NoArbFlag:
    if bf_value is None:
        return NoArbFlag(check="BUTTERFLY_CONVEXITY", passed=True, detail=f"BF{delta_label} unavailable, skipped")
    passed = bf_value >= tolerance
    return NoArbFlag(
        check="BUTTERFLY_CONVEXITY",
        passed=passed,
        detail=f"BF{delta_label} = {bf_value:.4f} ({'consistent' if passed else 'below convexity tolerance'})",
    )


def check_bid_ask(bid: float, ask: float) -> NoArbFlag:
    passed = ask >= bid >= 0
    return NoArbFlag(check="BID_ASK_CONSISTENCY", passed=passed, detail=f"bid={bid}, ask={ask}")
