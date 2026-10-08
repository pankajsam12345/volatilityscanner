"""
IV smile construction and delta-space interpolation (§11).

Builds an OTM smile per expiry: strikes below spot use put IV/delta, strikes
above spot use call IV/delta (standard OTM-only smile convention — avoids
mixing the less liquid ITM side). Interpolates in |delta| space so "25-delta
put" / "25-delta call" / ATM (delta≈0.50) figures can be read off directly,
which is what skew/RR/BF (§12-14) are built from.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True)
class SmilePoint:
    strike: float
    iv: float
    delta: float  # signed: positive for calls, negative for puts
    option_type: str


@dataclass(frozen=True)
class SmileData:
    atm_iv: float | None
    call_wing_delta: np.ndarray  # ascending abs(delta), 0..0.5
    call_wing_iv: np.ndarray
    put_wing_delta: np.ndarray  # ascending abs(delta), 0..0.5
    put_wing_iv: np.ndarray

    def call_iv_at_delta(self, target_abs_delta: float) -> float | None:
        return _interp_safe(target_abs_delta, self.call_wing_delta, self.call_wing_iv)

    def put_iv_at_delta(self, target_abs_delta: float) -> float | None:
        return _interp_safe(target_abs_delta, self.put_wing_delta, self.put_wing_iv)


def _interp_safe(x: float, xp: np.ndarray, fp: np.ndarray) -> float | None:
    if xp.size < 2:
        return None
    order = np.argsort(xp)
    xp_sorted, fp_sorted = xp[order], fp[order]
    if x < xp_sorted[0] or x > xp_sorted[-1]:
        return None  # do not extrapolate beyond observed delta range
    return float(np.interp(x, xp_sorted, fp_sorted))


def build_smile(points: list[SmilePoint], spot: float) -> SmileData:
    calls = [p for p in points if p.option_type == "CALL" and p.strike >= spot]
    puts = [p for p in points if p.option_type == "PUT" and p.strike <= spot]

    call_delta = np.array([abs(p.delta) for p in calls], dtype=float)
    call_iv = np.array([p.iv for p in calls], dtype=float)
    put_delta = np.array([abs(p.delta) for p in puts], dtype=float)
    put_iv = np.array([p.iv for p in puts], dtype=float)

    call_atm = _interp_safe(0.5, call_delta, call_iv)
    put_atm = _interp_safe(0.5, put_delta, put_iv)
    if call_atm is not None and put_atm is not None:
        atm = (call_atm + put_atm) / 2
    else:
        atm = call_atm if call_atm is not None else put_atm

    return SmileData(
        atm_iv=atm,
        call_wing_delta=call_delta,
        call_wing_iv=call_iv,
        put_wing_delta=put_delta,
        put_wing_iv=put_iv,
    )


def strike_for_target_delta(
    spot: float,
    t_years: float,
    rate: float,
    dividend_yield: float,
    target_delta: float,
    iv_fn: Callable[[float], float],
    iterations: int = 4,
) -> tuple[float, float]:
    """
    Inverts BS delta -> strike for a given IV *function of strike* (a smile),
    via fixed-point iteration on d1 = Φ^-1(delta) [call] / -Φ^-1(|delta|) [put].
    Converges in a few iterations because equity-index smiles are close to
    linear-in-moneyness. Returns (strike, iv_at_that_strike). Used to build a
    smile analytically from a parametric vol surface without needing a full
    option chain + numerical IV solve for every historical day (§59 seeding).
    """
    abs_d = abs(target_delta)
    d1 = norm.ppf(abs_d) if target_delta > 0 else -norm.ppf(abs_d)
    sigma = iv_fn(spot)
    strike = spot
    for _ in range(iterations):
        m = (rate - dividend_yield + 0.5 * sigma * sigma) * t_years - d1 * sigma * math.sqrt(t_years)
        strike = spot * math.exp(m)
        sigma = iv_fn(strike)
    return strike, sigma


def delta_grid_ivs(smile: SmileData, deltas: list[int]) -> dict[str, float | None]:
    """{"call_25d_iv": ..., "put_25d_iv": ..., ...} for each configured delta bucket."""
    out: dict[str, float | None] = {}
    for d in deltas:
        out[f"call_{d}d_iv"] = smile.call_iv_at_delta(d / 100)
        out[f"put_{d}d_iv"] = smile.put_iv_at_delta(d / 100)
    return out
