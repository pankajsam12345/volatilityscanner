"""
Pure expiry-payoff math for the Strategy Builder (§34): payoff curve across
a spot grid, breakevens, and a numerical undefined-risk/-reward test (does
the payoff still have a nonzero slope at the grid's edges, i.e. would
extending the grid keep changing the max/min).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.analytics.black_scholes import intrinsic_value


@dataclass(frozen=True)
class PayoffLeg:
    strike: float
    option_type: str  # CALL | PUT
    action: str  # BUY | SELL
    entry_price: float  # mid price at which the leg was resolved
    quantity: int


def leg_pnl_at_expiry(spot: float, leg: PayoffLeg) -> float:
    intrinsic = intrinsic_value(spot, leg.strike, leg.option_type)
    if leg.action == "BUY":
        return (intrinsic - leg.entry_price) * leg.quantity
    return (leg.entry_price - intrinsic) * leg.quantity


def default_spot_grid(spot: float, n: int = 401, lower_mult: float = 0.02, upper_mult: float = 2.0) -> list[float]:
    return list(np.linspace(spot * lower_mult, spot * upper_mult, n))


def payoff_curve(legs: list[PayoffLeg], spot_grid: list[float]) -> list[tuple[float, float]]:
    return [(s, sum(leg_pnl_at_expiry(s, leg) for leg in legs)) for s in spot_grid]


def find_breakevens(curve: list[tuple[float, float]]) -> list[float]:
    breakevens = []
    for (s0, p0), (s1, p1) in zip(curve, curve[1:]):
        if p0 == 0:
            breakevens.append(s0)
        elif p0 * p1 < 0:
            # linear interpolation for the zero-crossing
            breakevens.append(s0 + (0 - p0) * (s1 - s0) / (p1 - p0))
    return breakevens


def _net_call_exposure(legs: list[PayoffLeg]) -> float:
    """sum(±quantity) over CALL legs only — the only thing that determines
    S→∞ boundedness, since a put's intrinsic value vanishes (not diverges)
    as spot rises, and is capped at its strike (not diverges) as spot falls
    to its floor of zero. A long call at any size makes the upside genuinely
    unbounded (undefined_reward); a net short call makes the downside
    genuinely unbounded (undefined_risk) — this is an algebraic fact about
    the payoff, not a numerical guess from a finite grid's edge slope."""
    sign = {"BUY": 1, "SELL": -1}
    return sum(sign[leg.action] * leg.quantity for leg in legs if leg.option_type == "CALL")


def risk_reward_bounds(legs: list[PayoffLeg], curve: list[tuple[float, float]]) -> dict:
    """
    {"max_risk": float|None, "max_reward": float|None, "undefined_risk": bool,
    "undefined_reward": bool}. Boundedness is decided analytically from the
    leg composition (see _net_call_exposure) — a put-only or fully
    call-hedged structure is *always* bounded on both sides for standard
    (non-negative-strike) options, since spot's floor is zero. The curve is
    only used to read off the numeric bound once we know it exists — never
    to guess whether one exists, which a finite grid can't reliably tell you
    (the true asymptote may lie past the grid's edge).
    """
    net_call_exposure = _net_call_exposure(legs)
    undefined_reward = net_call_exposure > 0
    undefined_risk = net_call_exposure < 0

    pnls = [p for _, p in curve]
    return {
        "max_risk": None if undefined_risk else float(-min(pnls)),
        "max_reward": None if undefined_reward else float(max(pnls)),
        "undefined_risk": undefined_risk,
        "undefined_reward": undefined_reward,
    }
