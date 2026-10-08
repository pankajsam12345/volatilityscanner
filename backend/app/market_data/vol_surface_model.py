"""
Parametric synthetic vol-surface generator shared by MockProvider (a single
"live" tick) and the synthetic seed generator (~260 days of history). Not a
calibration engine — a deliberately simple, self-consistent generator whose
output is always tagged DEMO DATA, never presented as real market data.

Per tenor bucket: IV(K, T) = atm_vol + skew_b * log_moneyness + curvature_c * log_moneyness^2
where log_moneyness = ln(K / spot). Surface state evolves day-to-day as a
mean-reverting AR(1) process, mildly negatively correlated with the spot
return (volatility tends to rise when spot falls — the leverage effect),
which is what gives the historical percentile/relative-value engine a
realistic-looking distribution to compare "today" against.
"""
from __future__ import annotations

import datetime as dt
import zlib
from dataclasses import dataclass, field

import numpy as np

TENOR_DAYS = [7, 14, 30, 60, 90, 180, 270, 365]


def stable_seed(s: str) -> int:
    """
    A process-independent string seed for np.random.default_rng.

    Python's builtin hash() is randomized per-process (PYTHONHASHSEED) for
    security, so `hash("NIFTY")` differs across the API process, the Celery
    worker process, and every process restart. Using it here would silently
    make "deterministic" demo-data generation different every time a
    different process touches the same symbol — e.g. the Celery worker's
    live refresh would build an entirely different (and historically
    inconsistent) vol surface than the one scripts/seed.py used to backfill
    history, producing nonsensical live-vs-history deviations. crc32 has no
    such randomization.
    """
    return zlib.crc32(s.encode())


@dataclass
class UnderlyingProfile:
    symbol: str
    exchange: str
    spot: float
    lot_size: int
    strike_step: float
    atm_base: float  # base ATM vol level, e.g. 0.13 for 13%
    daily_return_vol: float  # roughly consistent with atm_base, drives RV


DEFAULT_PROFILES: dict[str, UnderlyingProfile] = {
    "NIFTY": UnderlyingProfile("NIFTY", "NSE", 24800.0, 50, 50.0, 0.13, 0.0095),
    "BANKNIFTY": UnderlyingProfile("BANKNIFTY", "NSE", 51500.0, 15, 100.0, 0.16, 0.012),
    "SPX": UnderlyingProfile("SPX", "CBOE", 5650.0, 100, 5.0, 0.14, 0.009),
}


@dataclass
class TenorSurface:
    tenor_days: int
    atm_vol: float
    skew_b: float
    curvature_c: float


@dataclass
class DailySurface:
    as_of: dt.date
    spot: float
    tenors: dict[int, TenorSurface] = field(default_factory=dict)

    def smile_iv(self, tenor_days: int, strike: float) -> float:
        t = self.tenors[tenor_days]
        log_moneyness = np.log(strike / self.spot)
        iv = t.atm_vol + t.skew_b * log_moneyness + t.curvature_c * log_moneyness ** 2
        return float(max(iv, 0.02))


def init_surface(as_of: dt.date, profile: UnderlyingProfile, rng: np.random.Generator) -> DailySurface:
    tenors: dict[int, TenorSurface] = {}
    for td in TENOR_DAYS:
        t_years = td / 365.0
        # Mild upward-sloping term structure (contango) by default, with a
        # touch of curvature so the very front and very back aren't linear.
        term_slope = 0.02 * np.sqrt(t_years)
        atm = profile.atm_base + term_slope + rng.normal(0, 0.005)
        skew_b = -0.06 - 0.01 * np.sqrt(t_years) + rng.normal(0, 0.005)  # negative: put skew (equity-index typical)
        curvature_c = 0.10 + rng.normal(0, 0.01)
        tenors[td] = TenorSurface(td, max(atm, 0.03), skew_b, max(curvature_c, 0.0))
    return DailySurface(as_of=as_of, spot=profile.spot, tenors=tenors)


def evolve_surface(
    prev: DailySurface,
    next_date: dt.date,
    profile: UnderlyingProfile,
    rng: np.random.Generator,
    mean_reversion: float = 0.03,
    vol_of_vol: float = 0.012,
) -> DailySurface:
    spot_ret = rng.normal(-0.5 * profile.daily_return_vol ** 2, profile.daily_return_vol)
    new_spot = float(prev.spot * np.exp(spot_ret))

    # Leverage effect: a negative spot return nudges vol up.
    vol_shock = -2.5 * spot_ret

    tenors: dict[int, TenorSurface] = {}
    for td in TENOR_DAYS:
        t_years = td / 365.0
        long_run_atm = profile.atm_base + 0.02 * np.sqrt(t_years)
        prev_t = prev.tenors[td]
        atm = (
            prev_t.atm_vol
            + mean_reversion * (long_run_atm - prev_t.atm_vol)
            + vol_of_vol * vol_shock * (1.0 / (1 + 2 * t_years))  # front tenor reacts more
            + rng.normal(0, vol_of_vol)
        )
        skew_b = prev_t.skew_b + 0.05 * ((-0.06 - 0.01 * np.sqrt(t_years)) - prev_t.skew_b) + rng.normal(0, 0.003)
        curvature_c = prev_t.curvature_c + 0.05 * (0.10 - prev_t.curvature_c) + rng.normal(0, 0.005)
        tenors[td] = TenorSurface(td, max(atm, 0.03), skew_b, max(curvature_c, 0.0))

    return DailySurface(as_of=next_date, spot=new_spot, tenors=tenors)


def surface_to_state(surface: DailySurface) -> dict:
    """Serializes the per-tenor AR(1) state (not spot/as_of, which the caller
    already tracks separately) so a DailySurface can be persisted and later
    resumed via `state_to_surface` — see mock_provider.py's day-to-day
    continuity fix."""
    return {
        str(td): {"atm_vol": t.atm_vol, "skew_b": t.skew_b, "curvature_c": t.curvature_c}
        for td, t in surface.tenors.items()
    }


def state_to_surface(as_of: dt.date, spot: float, state: dict) -> DailySurface:
    tenors = {
        int(td): TenorSurface(int(td), s["atm_vol"], s["skew_b"], s["curvature_c"])
        for td, s in state.items()
    }
    return DailySurface(as_of=as_of, spot=spot, tenors=tenors)


def nearest_tenor_days(days_to_expiry: int) -> int:
    return min(TENOR_DAYS, key=lambda td: abs(td - days_to_expiry))


def expiry_dates_from(as_of: dt.date) -> list[dt.date]:
    dates = []
    for td in TENOR_DAYS:
        d = as_of + dt.timedelta(days=td)
        while d.weekday() >= 5:  # roll off weekends
            d += dt.timedelta(days=1)
        dates.append(d)
    return dates


def strike_grid(spot: float, strike_step: float, n_each_side: int = 20) -> list[float]:
    atm_strike = round(spot / strike_step) * strike_step
    return [atm_strike + i * strike_step for i in range(-n_each_side, n_each_side + 1)]
