"""
Queries the pre-computed historical distributions (MetricHistory,
HistoricalVolatility) that back every z-score/percentile/fair-value
calculation (§18/§48). Keeping this thin and DB-only lets the analytics
layer stay pure and independently testable.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HistoricalVolatility, MetricHistory, Underlying


async def get_underlying_id(session: AsyncSession, symbol: str) -> int | None:
    result = await session.execute(select(Underlying.id).where(Underlying.symbol == symbol))
    return result.scalar_one_or_none()


async def get_metric_history(
    session: AsyncSession, underlying_id: int, metric_name: str, bucket: str = "",
) -> list[float]:
    stmt = (
        select(MetricHistory.value)
        .where(
            MetricHistory.underlying_id == underlying_id,
            MetricHistory.metric_name == metric_name,
            MetricHistory.bucket == bucket,
        )
        .order_by(MetricHistory.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_metric_history_with_timestamps(
    session: AsyncSession, underlying_id: int, metric_name: str, bucket: str = "",
) -> list[tuple]:
    stmt = (
        select(MetricHistory.timestamp, MetricHistory.value)
        .where(
            MetricHistory.underlying_id == underlying_id,
            MetricHistory.metric_name == metric_name,
            MetricHistory.bucket == bucket,
        )
        .order_by(MetricHistory.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def get_hv_series(
    session: AsyncSession, underlying_id: int, window: int, estimator: str = "CLOSE_CLOSE",
) -> list[tuple]:
    """Returns [(timestamp, hv_value), ...] for the given trailing window (5/10/20/30/60/90/252)."""
    column = getattr(HistoricalVolatility, f"hv_{window}")
    stmt = (
        select(HistoricalVolatility.timestamp, column)
        .where(HistoricalVolatility.underlying_id == underlying_id, HistoricalVolatility.estimator == estimator)
        .order_by(HistoricalVolatility.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def get_latest_hv(
    session: AsyncSession, underlying_id: int, window: int, estimator: str = "CLOSE_CLOSE",
) -> float | None:
    series = await get_hv_series(session, underlying_id, window, estimator)
    for _, value in reversed(series):
        if value is not None:
            return value
    return None


async def get_aligned_iv_rv_history(
    session: AsyncSession, underlying_id: int, tenor_label: str, rv_window: int = 20,
) -> tuple[list[float], list[float]]:
    """Same-day-aligned (IV, RV) series for the IV/RV fair-value regression and z-score."""
    iv_rows = await get_metric_history_with_timestamps(session, underlying_id, "atm_iv", tenor_label)
    hv_rows = await get_hv_series(session, underlying_id, rv_window, "CLOSE_CLOSE")
    hv_by_ts = {ts: v for ts, v in hv_rows if v is not None}

    iv_history, rv_history = [], []
    for ts, iv in iv_rows:
        if iv is None:
            continue
        rv = hv_by_ts.get(ts)
        if rv is not None:
            iv_history.append(iv)
            rv_history.append(rv)
    return iv_history, rv_history


async def get_aligned_iv_rv_series_with_dates(
    session: AsyncSession, underlying_id: int, tenor_label: str, rv_window: int = 20,
) -> tuple[list, list[float], list[float]]:
    """Same as get_aligned_iv_rv_history but also returns each observation's date — needed by the backtester."""
    iv_rows = await get_metric_history_with_timestamps(session, underlying_id, "atm_iv", tenor_label)
    hv_rows = await get_hv_series(session, underlying_id, rv_window, "CLOSE_CLOSE")
    hv_by_ts = {ts: v for ts, v in hv_rows if v is not None}

    dates, iv_history, rv_history = [], [], []
    for ts, iv in iv_rows:
        if iv is None:
            continue
        rv = hv_by_ts.get(ts)
        if rv is not None:
            dates.append(ts.date())
            iv_history.append(iv)
            rv_history.append(rv)
    return dates, iv_history, rv_history
