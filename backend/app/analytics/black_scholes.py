"""
Black-Scholes-Merton pricing, Greeks, and put-call parity.

Pure functions only — no DB/FastAPI imports — so this module (and the rest
of `app.analytics`) is independently unit-testable per spec §58.

Conventions:
  S      spot price
  K      strike
  T      time to expiry, in years
  r      continuously-compounded risk-free rate
  q      continuously-compounded dividend yield
  sigma  annualized volatility (e.g. 0.20 for 20%)

Vega and vanna/volga below are expressed "per 1.00 (100 vol points) change
in sigma" — divide by 100 to get the conventional "per 1 vol point" figure.
Theta is expressed per calendar year — divide by 365 (or 252 for trading-day
theta) for a daily figure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from scipy.stats import norm

OptionSide = Literal["CALL", "PUT"]


@dataclass(frozen=True)
class BSInputs:
    spot: float
    strike: float
    time_to_expiry: float  # years
    rate: float
    dividend_yield: float
    sigma: float
    option_type: OptionSide


def d1_d2(spot: float, strike: float, t: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        raise ValueError("spot, strike, time_to_expiry, and sigma must all be positive")
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


# Backwards-compatible private alias used internally in this module.
_d1_d2 = d1_d2


def price(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    if inputs.option_type == "CALL":
        return S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    return K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)


def intrinsic_value(spot: float, strike: float, option_type: OptionSide) -> float:
    return max(spot - strike, 0.0) if option_type == "CALL" else max(strike - spot, 0.0)


def delta(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, _ = _d1_d2(S, K, T, r, q, sigma)
    disc_q = math.exp(-q * T)
    if inputs.option_type == "CALL":
        return disc_q * norm.cdf(d1)
    return -disc_q * norm.cdf(-d1)


def gamma(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, _ = _d1_d2(S, K, T, r, q, sigma)
    return math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))


def vega(inputs: BSInputs) -> float:
    """Per 1.00 (100 vol points) change in sigma."""
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, _ = _d1_d2(S, K, T, r, q, sigma)
    return S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T)


def theta(inputs: BSInputs) -> float:
    """Per calendar year. Divide by 365 for a daily figure."""
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    term1 = -(S * disc_q * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if inputs.option_type == "CALL":
        return term1 - r * K * disc_r * norm.cdf(d2) + q * S * disc_q * norm.cdf(d1)
    return term1 + r * K * disc_r * norm.cdf(-d2) - q * S * disc_q * norm.cdf(-d1)


def rho(inputs: BSInputs) -> float:
    """Per 1.00 (100%) change in rate."""
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    _, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_r = math.exp(-r * T)
    if inputs.option_type == "CALL":
        return K * T * disc_r * norm.cdf(d2)
    return -K * T * disc_r * norm.cdf(-d2)


def put_call_parity_deviation(
    call_price: float, put_price: float, spot: float, strike: float,
    t: float, r: float, q: float = 0.0,
) -> float:
    """
    C - P vs S*e^-qT - K*e^-rT.  Returns the deviation (should be ~0);
    a large deviation signals a data/quote problem, not a real arbitrage
    (real-world bid/ask and financing frictions make small deviations normal).
    """
    lhs = call_price - put_price
    rhs = spot * math.exp(-q * t) - strike * math.exp(-r * t)
    return lhs - rhs
