"""
Portfolio-level risk aggregation + what-if simulator (§39-40).

VaR/CVaR here are a **parametric delta-vega ("delta-normal") approximation**
— it treats the spot-driven and vega-driven daily P&L as independent normal
sources and ignores gamma's contribution to the variance (gamma P&L isn't
normally distributed, and a fully correct closed form needs the portfolio's
full return distribution). This is a standard, named, and clearly-labeled
simplification — not a full historical-simulation VaR — appropriate for a
quick risk snapshot; §41's Monte Carlo simulator is the tool for a genuine
P&L distribution on a single strategy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.opportunities.greeks_aggregator import GREEK_KEYS
from app.simulation.pnl_attribution import attribute_pnl

Z_95 = 1.6448536269514722  # one-tailed 95% normal quantile
ES_95_MULTIPLIER = 2.0627128330566093  # E[Z | Z > z_0.95] for a standard normal


@dataclass(frozen=True)
class ParametricRisk:
    daily_std: float
    var_95: float
    cvar_95: float


def aggregate_position_greeks(position_legs_greeks: list[list[dict]], quantities: list[int]) -> dict:
    """position_legs_greeks[i] is the list of per-leg greek dicts for position i; quantities[i] scales that whole position."""
    totals = {k: 0.0 for k in GREEK_KEYS}
    for leg_greeks_list, qty in zip(position_legs_greeks, quantities):
        for leg_greeks in leg_greeks_list:
            for k in GREEK_KEYS:
                v = leg_greeks.get(k)
                if v is not None:
                    totals[k] += v * qty
    return totals


def parametric_var(
    delta: float, vega: float, spot: float, daily_spot_vol: float, daily_vol_of_vol_points: float,
) -> ParametricRisk:
    delta_pnl_std = abs(delta) * spot * daily_spot_vol
    vega_pnl_std = abs(vega) * (daily_vol_of_vol_points / 100.0)
    daily_std = float(np.sqrt(delta_pnl_std ** 2 + vega_pnl_std ** 2))
    return ParametricRisk(daily_std=daily_std, var_95=daily_std * Z_95, cvar_95=daily_std * ES_95_MULTIPLIER)


def what_if_grid(
    greeks: dict, net_premium: float, rate: float, reference_spot: float,
    spot_shocks_pct: list[float], vol_shocks_pts: list[float], time_shocks_days: list[int],
) -> list[dict]:
    """reference_spot converts each spot shock (a %) into the absolute dS attribute_pnl needs."""
    cells = []
    for spot_pct in spot_shocks_pct:
        d_spot = reference_spot * spot_pct
        for vol_pts in vol_shocks_pts:
            for days in time_shocks_days:
                pnl = attribute_pnl(greeks, net_premium, d_spot, vol_pts, float(days), rate).total
                cells.append({"spot_shock_pct": spot_pct, "vol_shock_pts": vol_pts, "time_shock_days": days, "pnl": pnl})
    return cells
