"""
Delta-hedge simulator with P&L attribution (§17/§35).

Rather than re-pricing the position from scratch at every step (which would
need a full smile reconstruction), this holds the position's Greeks fixed
at their current (t=0) values and applies the 2nd-order Taylor
decomposition (app.simulation.pnl_attribution) to each simulated step's
realized (dSpot, dSigma, dt) — a standard, clearly-labeled approximation.
Rehedging frequency is modeled by subdividing each simulated day into N
equal sub-steps (5-minute rehedging ≈ daily split into ~84 sub-steps rather
than genuine tick-level simulation) — more frequent rehedging reduces the
P&L variance from discrete hedging error, the textbook gamma-scalping
result this is meant to demonstrate.

The spot/vol path reuses the same leverage-correlated mean-reverting model
as app.market_data.vol_surface_model (vol tends to rise when spot falls),
just applied to a single scalar "representative" sigma rather than a full
tenor/strike surface, since only the position's already-known Greeks (not a
fresh smile) are needed to drive the attribution.
"""
from __future__ import annotations

import math

import numpy as np

from app.simulation.pnl_attribution import attribute_pnl

FREQUENCY_STEPS_PER_DAY = {"daily": 1, "hourly": 7, "30min": 14, "15min": 28, "5min": 84}
PNL_COMPONENT_KEYS = ("spot_pnl", "gamma_pnl", "theta_pnl", "vega_pnl", "vanna_pnl", "volga_pnl", "carry_pnl")


def simulate_hedge(
    greeks: dict,
    net_premium: float,
    spot0: float,
    sigma0_vol_points: float,
    rate: float,
    daily_spot_vol: float,
    num_days: int,
    rehedge_frequency: str,
    hedge_cost_bps: float = 0.0005,
    vol_of_vol_points: float = 0.3,
    mean_reversion: float = 0.05,
    seed: int = 7,
) -> dict:
    if rehedge_frequency not in FREQUENCY_STEPS_PER_DAY:
        raise ValueError(f"Unknown rehedge_frequency '{rehedge_frequency}'. Options: {list(FREQUENCY_STEPS_PER_DAY)}")

    steps_per_day = FREQUENCY_STEPS_PER_DAY[rehedge_frequency]
    dt_sub_days = 1.0 / steps_per_day
    rng = np.random.default_rng(seed)

    spot, sigma = spot0, sigma0_vol_points
    cumulative_totals = {k: 0.0 for k in (*PNL_COMPONENT_KEYS, "transaction_cost")}
    daily_records = []

    for day in range(1, num_days + 1):
        day_totals = {k: 0.0 for k in cumulative_totals}

        for _ in range(steps_per_day):
            spot_shock = rng.normal(-0.5 * daily_spot_vol ** 2 * dt_sub_days, daily_spot_vol * math.sqrt(dt_sub_days))
            new_spot = spot * math.exp(spot_shock)
            d_spot = new_spot - spot

            vol_shock = -2.5 * spot_shock  # leverage effect: vol rises when spot falls
            new_sigma = (
                sigma + mean_reversion * (sigma0_vol_points - sigma)
                + vol_of_vol_points * vol_shock * math.sqrt(dt_sub_days)
                + rng.normal(0, vol_of_vol_points * math.sqrt(dt_sub_days))
            )
            d_sigma = new_sigma - sigma

            attribution = attribute_pnl(greeks, net_premium, d_spot, d_sigma, dt_sub_days, rate)
            for key in PNL_COMPONENT_KEYS:
                day_totals[key] += getattr(attribution, key)

            # Rehedge: the incremental delta drift since the last hedge (from
            # gamma and vanna) is what needs offsetting to return to flat.
            delta_drift = (greeks.get("gamma", 0.0) or 0.0) * d_spot + (greeks.get("vanna", 0.0) or 0.0) * (d_sigma / 100.0)
            day_totals["transaction_cost"] += abs(delta_drift) * new_spot * hedge_cost_bps

            spot, sigma = new_spot, new_sigma

        for key in cumulative_totals:
            cumulative_totals[key] += day_totals[key]

        gross = sum(day_totals[k] for k in PNL_COMPONENT_KEYS)
        daily_records.append({
            "day": day, "spot_pnl": day_totals["spot_pnl"], "gamma_pnl": day_totals["gamma_pnl"],
            "theta_pnl": day_totals["theta_pnl"], "vega_pnl": day_totals["vega_pnl"],
            "carry": day_totals["carry_pnl"], "transaction_cost": day_totals["transaction_cost"],
            "net_pnl": gross - day_totals["transaction_cost"],
        })

    totals = dict(cumulative_totals)
    totals["gross_pnl"] = sum(cumulative_totals[k] for k in PNL_COMPONENT_KEYS)
    totals["net_pnl"] = totals["gross_pnl"] - cumulative_totals["transaction_cost"]

    return {"rehedge_frequency": rehedge_frequency, "num_days": num_days, "cumulative": daily_records, "totals": totals}
