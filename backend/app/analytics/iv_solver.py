"""
Implied volatility solver.

Never silently returns a number: every call returns an IVResult carrying an
explicit status (§6). Callers must check `status == IVStatus.VALID` before
trusting `iv`.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Optional

from scipy.optimize import brentq

from app.analytics.black_scholes import BSInputs, OptionSide, intrinsic_value, price


class IVStatus(str, enum.Enum):
    VALID = "VALID"
    NO_CONVERGENCE = "NO_CONVERGENCE"
    INVALID_PRICE = "INVALID_PRICE"
    WIDE_SPREAD = "WIDE_SPREAD"
    ARBITRAGE_VIOLATION = "ARBITRAGE_VIOLATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class IVResult:
    iv: Optional[float]
    status: IVStatus
    error: Optional[str] = None


def solve_iv(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    dividend_yield: float,
    option_type: OptionSide,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    min_bound: float = 0.001,
    max_bound: float = 5.0,
    max_iter: int = 100,
    tol: float = 1e-6,
    wide_spread_pct_threshold: float = 25.0,
) -> IVResult:
    if time_to_expiry is None or time_to_expiry <= 0:
        return IVResult(None, IVStatus.INSUFFICIENT_DATA, "Option has expired or T<=0")

    if spot is None or strike is None or spot <= 0 or strike <= 0:
        return IVResult(None, IVStatus.INSUFFICIENT_DATA, "Missing or non-positive spot/strike")

    if market_price is None or market_price <= 0 or not math.isfinite(market_price):
        return IVResult(None, IVStatus.INVALID_PRICE, "Non-positive or missing option price")

    floor = intrinsic_value(spot, strike, option_type) * math.exp(-dividend_yield * time_to_expiry)
    # Slightly loose tolerance to allow for discretization; below this it's a
    # genuine violation of the lower no-arbitrage bound, not just noise.
    if market_price < floor - 1e-6:
        return IVResult(
            None, IVStatus.ARBITRAGE_VIOLATION,
            f"Price {market_price:.4f} below intrinsic/no-arbitrage floor {floor:.4f}",
        )

    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_pct = (ask - bid) / mid * 100
            if spread_pct > wide_spread_pct_threshold:
                return IVResult(
                    None, IVStatus.WIDE_SPREAD,
                    f"Bid/ask spread {spread_pct:.1f}% exceeds {wide_spread_pct_threshold:.1f}% threshold",
                )
        if bid > ask:
            return IVResult(None, IVStatus.ARBITRAGE_VIOLATION, "Bid > ask")

    def objective(sigma: float) -> float:
        inputs = BSInputs(spot, strike, time_to_expiry, rate, dividend_yield, sigma, option_type)
        return price(inputs) - market_price

    try:
        lo, hi = objective(min_bound), objective(max_bound)
        if lo * hi > 0:
            return IVResult(
                None, IVStatus.NO_CONVERGENCE,
                f"Price {market_price:.4f} not bracketed by sigma in [{min_bound}, {max_bound}]",
            )
        iv = brentq(objective, min_bound, max_bound, xtol=tol, maxiter=max_iter)
        return IVResult(iv, IVStatus.VALID)
    except (ValueError, RuntimeError) as exc:
        return IVResult(None, IVStatus.NO_CONVERGENCE, str(exc))
