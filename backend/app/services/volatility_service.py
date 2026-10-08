"""
Builds a per-expiry volatility snapshot (smile, ATM IV, skew/RR/BF grid)
from the most recent real VolatilitySnapshot/Option rows for that expiry.
Shared by the opportunity engine and the read-only volatility/term-structure/
skew/etc. API routers, so both see exactly the same numbers.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.butterfly import butterfly_metrics
from app.analytics.stats import distribution_context
from app.analytics.risk_reversal import risk_reversal_metrics
from app.analytics.skew import skew_metrics
from app.analytics.smile import SmileData, SmilePoint, build_smile, delta_grid_ivs
from app.market_data.vol_surface_model import TENOR_DAYS
from app.models import Expiry, Option, Underlying, VolatilitySnapshot

TENOR_LABEL = {7: "1W", 14: "2W", 30: "1M", 60: "2M", 90: "3M", 180: "6M", 270: "9M", 365: "1Y"}


def nearest_tenor_label(days_to_expiry: int) -> str:
    nearest = min(TENOR_DAYS, key=lambda td: abs(td - days_to_expiry))
    return TENOR_LABEL[nearest]


@dataclass
class ExpirySnapshot:
    expiry_id: int
    expiry_date: object
    tenor_label: str
    t_years: float
    timestamp: object
    smile: SmileData
    grid: dict
    skew: dict
    rr: dict
    bf: dict
    snapshot_by_key: dict = field(default_factory=dict)
    option_by_key: dict = field(default_factory=dict)

    def find_nearest_by_delta(self, option_type: str | None, target_abs_delta: float):
        """
        Nearest real (strike, option_type) snapshot to a target |delta|.
        option_type=None searches both sides (used for an "ATM" leg where
        either a call or a put near delta 0.5 is an acceptable proxy);
        pass a concrete "CALL"/"PUT" when the leg genuinely needs that side
        (e.g. a strategy-builder put leg). Returns (key, VolatilitySnapshot)
        or None if no snapshot with a solved delta exists on that side.
        """
        if option_type is None:
            candidates = [(k, v) for k, v in self.snapshot_by_key.items() if v.delta is not None]
        else:
            candidates = [
                (k, v) for k, v in self.snapshot_by_key.items()
                if v.delta is not None and v.option_type.value == option_type
            ]
        if not candidates:
            return None
        return min(candidates, key=lambda kv: abs(abs(kv[1].delta) - target_abs_delta))


async def build_expiry_snapshot(session: AsyncSession, underlying: Underlying, expiry: Expiry, settings) -> ExpirySnapshot | None:
    max_ts = (
        await session.execute(
            select(func.max(VolatilitySnapshot.timestamp)).where(VolatilitySnapshot.expiry_id == expiry.id)
        )
    ).scalar_one_or_none()
    if max_ts is None:
        return None

    snap_rows = (
        await session.execute(
            select(VolatilitySnapshot).where(VolatilitySnapshot.expiry_id == expiry.id, VolatilitySnapshot.timestamp == max_ts)
        )
    ).scalars().all()
    opt_rows = (
        await session.execute(select(Option).where(Option.expiry_id == expiry.id, Option.timestamp == max_ts))
    ).scalars().all()

    snapshot_by_key = {(r.strike, r.option_type.value): r for r in snap_rows}
    option_by_key = {(r.strike, r.option_type.value): r for r in opt_rows}

    points = [
        SmilePoint(strike=r.strike, iv=r.iv, delta=r.delta, option_type=r.option_type.value)
        for r in snap_rows if r.iv is not None and r.delta is not None
    ]
    if len(points) < 4:
        return None
    smile = build_smile(points, underlying.spot_price)
    if smile.atm_iv is None:
        return None

    grid = delta_grid_ivs(smile, settings.rr_bf_deltas)
    skew = skew_metrics(grid, smile.atm_iv, settings.rr_bf_deltas)
    rr = risk_reversal_metrics(grid, settings.rr_bf_deltas)
    bf = butterfly_metrics(grid, smile.atm_iv, settings.rr_bf_deltas)

    return ExpirySnapshot(
        expiry_id=expiry.id, expiry_date=expiry.expiry_date, tenor_label=nearest_tenor_label(expiry.days_to_expiry),
        t_years=max(expiry.days_to_expiry, 1) / 365.0, timestamp=max_ts,
        smile=smile, grid=grid, skew=skew, rr=rr, bf=bf,
        snapshot_by_key=snapshot_by_key, option_by_key=option_by_key,
    )


async def build_expiry_snapshot_as_of(session: AsyncSession, expiry_id: int, as_of_date: dt.date) -> ExpirySnapshot | None:
    """
    A lightweight variant of build_expiry_snapshot scoped to a specific
    historical calendar day instead of the latest — used by the
    chain-replay backtester to resolve/mark-to-market a strategy's legs on
    a specific past day. Only snapshot_by_key/option_by_key are populated
    (all resolve_legs/find_nearest_by_delta need — delta->strike lookup and
    bid/ask); the smile/skew/RR/BF fields the live volatility pages need
    are left empty, since rebuilding those correctly would also require
    that day's historical spot price (not persisted per-day) and replay
    never reads them. Every row this app writes is timestamped at a fixed
    15:30 close-of-day (see scripts/seed.py, snapshot_service.py), so an
    exact match is sufficient — no date-range fuzz needed.
    """
    ts = dt.datetime.combine(as_of_date, dt.time(15, 30))
    snap_rows = (
        await session.execute(
            select(VolatilitySnapshot).where(VolatilitySnapshot.expiry_id == expiry_id, VolatilitySnapshot.timestamp == ts)
        )
    ).scalars().all()
    if not snap_rows:
        return None
    opt_rows = (
        await session.execute(select(Option).where(Option.expiry_id == expiry_id, Option.timestamp == ts))
    ).scalars().all()
    if not opt_rows:
        return None

    return ExpirySnapshot(
        expiry_id=expiry_id, expiry_date=as_of_date, tenor_label="", t_years=0.0, timestamp=ts,
        smile=None, grid={}, skew={}, rr={}, bf={},
        snapshot_by_key={(r.strike, r.option_type.value): r for r in snap_rows},
        option_by_key={(r.strike, r.option_type.value): r for r in opt_rows},
    )


async def get_all_expiry_snapshots(session: AsyncSession, underlying: Underlying, settings) -> dict[int, ExpirySnapshot]:
    expiries = (
        await session.execute(
            select(Expiry)
            .where(Expiry.underlying_id == underlying.id, Expiry.source == "LIVE")
            .order_by(Expiry.days_to_expiry)
        )
    ).scalars().all()
    out: dict[int, ExpirySnapshot] = {}
    for expiry in expiries:
        es = await build_expiry_snapshot(session, underlying, expiry, settings)
        if es is not None:
            out[expiry.id] = es
    return out


async def metric_with_context(session: AsyncSession, underlying_id: int, metric_name: str, bucket: str, current_value: float | None) -> dict:
    """{"current": ..., "mean": ..., "median": ..., "std": ..., "percentile": ..., "zscore": ..., "sample_size": ...}"""
    from app.services import history_service  # local import: avoids a service-to-service import cycle at module load time

    history = await history_service.get_metric_history(session, underlying_id, metric_name, bucket)
    if current_value is None:
        return {"current": None, "mean": None, "median": None, "std": None, "percentile": None, "zscore": None, "sample_size": len(history)}
    ctx = distribution_context(current_value, history)
    if ctx is None:
        return {"current": current_value, "mean": None, "median": None, "std": None, "percentile": None, "zscore": None, "sample_size": len(history)}
    return {
        "current": ctx.current, "mean": ctx.mean, "median": ctx.median, "std": ctx.std,
        "percentile": ctx.percentile, "zscore": ctx.zscore, "sample_size": ctx.sample_size,
    }
