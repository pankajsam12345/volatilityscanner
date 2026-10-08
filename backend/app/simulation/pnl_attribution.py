"""
P&L decomposition via 2nd-order Taylor expansion of option value in
(spot, sigma, time) — §35. Pure function: given a position's aggregated
Greeks (per app.opportunities.greeks_aggregator convention: gamma/vega/vanna/
volga per the black_scholes.py scaling, theta already per calendar day) and
realized moves, splits the estimated P&L into named components.

This is an *approximation* — a 2nd-order Taylor expansion, not a full
repricing — accurate for small moves and clearly labeled as such wherever
it's surfaced (hedge simulator, portfolio risk, what-if simulator).

"Carry" here means financing cost/benefit on the position's net premium at
the configured risk-free rate — a distinct concept from theta (option time
decay), per §35's line-item list treating them separately.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PnLAttribution:
    spot_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    vanna_pnl: float
    volga_pnl: float
    carry_pnl: float
    total: float

    def as_dict(self) -> dict:
        return {
            "spot_pnl": self.spot_pnl, "gamma_pnl": self.gamma_pnl, "theta_pnl": self.theta_pnl,
            "vega_pnl": self.vega_pnl, "vanna_pnl": self.vanna_pnl, "volga_pnl": self.volga_pnl,
            "carry_pnl": self.carry_pnl, "total": self.total,
        }


def attribute_pnl(
    greeks: dict, net_premium: float, d_spot: float, d_sigma_vol_points: float,
    dt_days: float, rate: float,
) -> PnLAttribution:
    d_sigma = d_sigma_vol_points / 100.0

    delta = greeks.get("delta", 0.0) or 0.0
    gamma = greeks.get("gamma", 0.0) or 0.0
    theta = greeks.get("theta", 0.0) or 0.0
    vega = greeks.get("vega", 0.0) or 0.0
    vanna = greeks.get("vanna", 0.0) or 0.0
    volga = greeks.get("volga", 0.0) or 0.0

    spot_pnl = delta * d_spot
    gamma_pnl = 0.5 * gamma * d_spot ** 2
    theta_pnl = theta * dt_days
    vega_pnl = vega * d_sigma
    vanna_pnl = vanna * d_spot * d_sigma
    volga_pnl = 0.5 * volga * d_sigma ** 2
    carry_pnl = -rate * net_premium * (dt_days / 365.0)

    total = spot_pnl + gamma_pnl + theta_pnl + vega_pnl + vanna_pnl + volga_pnl + carry_pnl
    return PnLAttribution(spot_pnl, gamma_pnl, theta_pnl, vega_pnl, vanna_pnl, volga_pnl, carry_pnl, total)
