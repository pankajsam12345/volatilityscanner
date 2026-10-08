"""
Bridges the parametric DailySurface model to the analytics engine's smile/
skew/RR/BF functions *analytically* (via smile.strike_for_target_delta)
instead of generating a full option chain + running the IV solver.

Used exclusively for populating hundreds of days of historical distribution
context cheaply during seeding (§59). The live/current-day pipeline always
goes through the real path: option chain -> IV solver -> smile -> skew/RR/BF
(see services/snapshot_service.py) — this shortcut is never used for "today".
"""
from __future__ import annotations

import dataclasses

from app.analytics.butterfly import butterfly_metrics
from app.analytics.risk_reversal import risk_reversal_metrics
from app.analytics.skew import skew_metrics
from app.analytics.smile import SmileData, SmilePoint, build_smile, delta_grid_ivs, strike_for_target_delta
from app.market_data.vol_surface_model import DailySurface

DEFAULT_DELTAS = [10, 15, 25, 30]


def build_smile_from_surface(
    surface: DailySurface, tenor_days: int, rate: float, dividend_yield: float,
    deltas: list[int] = DEFAULT_DELTAS,
) -> SmileData:
    t_years = tenor_days / 365.0
    iv_fn = lambda k: surface.smile_iv(tenor_days, k)  # noqa: E731

    # ATM: call delta=+0.5 and put delta=-0.5 both resolve to the same d1=0,
    # hence the same strike — compute it once directly rather than through
    # the OTM-only wing filters (which would exclude whichever side that
    # strike doesn't satisfy strike>=/<=spot on).
    atm_strike, atm_iv = strike_for_target_delta(surface.spot, t_years, rate, dividend_yield, 0.5, iv_fn)

    points: list[SmilePoint] = []
    for d in deltas:
        frac = d / 100
        for sign, option_type in ((1, "CALL"), (-1, "PUT")):
            target = sign * frac
            strike, sigma = strike_for_target_delta(surface.spot, t_years, rate, dividend_yield, target, iv_fn)
            # Store the *target* delta (what we solved the strike for), not a
            # re-derived BS delta — the fixed-point solve converges very close
            # to, but not bit-exact with, the target, and re-deriving it can
            # push the boundary points (e.g. exactly 0.10) just outside the
            # interpolation range used by delta_grid_ivs.
            points.append(SmilePoint(strike=strike, iv=sigma, delta=target, option_type=option_type))

    smile = build_smile(points, surface.spot)
    return dataclasses.replace(smile, atm_iv=atm_iv)


def surface_metrics_for_tenor(
    surface: DailySurface, tenor_days: int, rate: float, dividend_yield: float,
    deltas: list[int] = DEFAULT_DELTAS,
) -> dict[str, float | None]:
    smile = build_smile_from_surface(surface, tenor_days, rate, dividend_yield, deltas)
    grid = delta_grid_ivs(smile, deltas)
    out: dict[str, float | None] = {"atm_iv": smile.atm_iv, **grid}
    out.update(skew_metrics(grid, smile.atm_iv, deltas))
    out.update(risk_reversal_metrics(grid, deltas))
    out.update(butterfly_metrics(grid, smile.atm_iv, deltas))
    return out
