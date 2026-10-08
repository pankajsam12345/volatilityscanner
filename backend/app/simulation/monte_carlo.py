"""
Monte Carlo P&L distribution (§41): GBM spot + a mean-reverting,
leverage-correlated stochastic-vol approximation (the same model idea as
app.market_data.vol_surface_model, applied to a scalar representative
sigma) for the underlying's move over the full horizon, then a single
2nd-order Taylor P&L attribution per path from the horizon-end
(dSpot, dSigma) — a terminal-distribution estimate, not a path-dependent
rehedged P&L (see hedge_simulator for that). Every caller must present
these as model-based estimates, never a guarantee.
"""
from __future__ import annotations

import numpy as np

from app.simulation.pnl_attribution import attribute_pnl


def simulate_monte_carlo(
    greeks: dict,
    net_premium: float,
    spot0: float,
    sigma0_vol_points: float,
    rate: float,
    daily_spot_vol: float,
    horizon_days: int,
    num_paths: int,
    vol_of_vol_points: float = 0.3,
    mean_reversion: float = 0.05,
    seed: int = 7,
) -> dict:
    rng = np.random.default_rng(seed)
    spot = np.full(num_paths, spot0, dtype=float)
    sigma = np.full(num_paths, sigma0_vol_points, dtype=float)

    for _ in range(horizon_days):
        spot_shock = rng.normal(-0.5 * daily_spot_vol ** 2, daily_spot_vol, num_paths)
        new_spot = spot * np.exp(spot_shock)
        vol_shock = -2.5 * spot_shock
        new_sigma = (
            sigma + mean_reversion * (sigma0_vol_points - sigma)
            + vol_of_vol_points * vol_shock + rng.normal(0, vol_of_vol_points, num_paths)
        )
        spot, sigma = new_spot, new_sigma

    d_spot = spot - spot0
    d_sigma = sigma - sigma0_vol_points

    pnls = np.array([
        attribute_pnl(greeks, net_premium, float(d_spot[i]), float(d_sigma[i]), float(horizon_days), rate).total
        for i in range(num_paths)
    ])

    p5 = float(np.percentile(pnls, 5))
    tail = pnls[pnls <= p5]

    return {
        "num_paths": num_paths,
        "horizon_days": horizon_days,
        "pnl_distribution_sample": pnls.tolist(),
        "mean_pnl": float(pnls.mean()),
        "var_95": float(-p5),
        "cvar_95": float(-tail.mean()) if tail.size else float(-p5),
        "prob_profit": float((pnls > 0).mean() * 100),
        "prob_loss": float((pnls <= 0).mean() * 100),
    }
