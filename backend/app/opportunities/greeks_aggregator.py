"""Aggregates per-leg Greeks into strategy/portfolio-level Greeks (§16/§25 "Portfolio Vega/Gamma/Theta/Delta")."""
from __future__ import annotations

GREEK_KEYS = ["delta", "gamma", "vega", "theta", "rho", "vanna", "volga", "charm"]
_SIGN = {"BUY": 1.0, "SELL": -1.0}


def aggregate_strategy_greeks(
    leg_actions: list[str], leg_greeks: list[dict[str, float]], leg_quantities: list[float] | None = None,
) -> dict[str, float]:
    quantities = leg_quantities or [1.0] * len(leg_actions)
    totals = {k: 0.0 for k in GREEK_KEYS}
    for action, greeks, qty in zip(leg_actions, leg_greeks, quantities):
        sign = _SIGN.get(action, 0.0) * qty
        for key in GREEK_KEYS:
            value = greeks.get(key)
            if value is not None:
                totals[key] += sign * value
    return totals
