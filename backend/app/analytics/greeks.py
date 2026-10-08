"""
Second- and third-order Black-Scholes Greeks (Haug, "The Complete Guide to
Option Pricing Formulas", 2nd ed.). Same units/scaling convention as
black_scholes.py: vanna/volga are "per 1.00 sigma", per-1.00-spot for
gamma/speed/zomma/color, per calendar year for charm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from app.analytics.black_scholes import BSInputs, d1_d2 as _d1_d2, gamma as bs_gamma, vega as bs_vega


@dataclass(frozen=True)
class FullGreeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    vanna: float
    volga: float
    charm: float
    speed: float
    color: float
    zomma: float


def vanna(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    return -math.exp(-q * T) * norm.pdf(d1) * d2 / sigma


def volga(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    return bs_vega(inputs) * d1 * d2 / sigma


def charm(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_q = math.exp(-q * T)
    common = -disc_q * norm.pdf(d1) * (2 * (r - q) * T - d2 * sigma * math.sqrt(T)) / (2 * T * sigma * math.sqrt(T))
    if inputs.option_type == "CALL":
        return common - q * disc_q * norm.cdf(d1)
    return common + q * disc_q * norm.cdf(-d1)


def speed(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, _ = _d1_d2(S, K, T, r, q, sigma)
    g = bs_gamma(inputs)
    return -g / S * (d1 / (sigma * math.sqrt(T)) + 1)


def zomma(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    g = bs_gamma(inputs)
    return g * (d1 * d2 - 1) / sigma


def color(inputs: BSInputs) -> float:
    S, K, T, r, q, sigma = (
        inputs.spot, inputs.strike, inputs.time_to_expiry,
        inputs.rate, inputs.dividend_yield, inputs.sigma,
    )
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_q = math.exp(-q * T)
    term = 2 * q * T + 1 + (2 * (r - q) * T - d2 * sigma * math.sqrt(T)) * d1 / (sigma * math.sqrt(T))
    return -disc_q * norm.pdf(d1) / (2 * S * T * sigma * math.sqrt(T)) * term
