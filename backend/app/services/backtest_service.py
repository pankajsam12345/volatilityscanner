"""Wires the pure backtesting engine to real stored history and persists results (§36-37)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.regime import classify_regime
from app.backtesting.chain_replay import replay_strategy_trades
from app.backtesting.engine import Trade, find_trade_windows, run_backtest
from app.backtesting.stats import compute_summary, equity_curve, regime_breakdown
from app.models import BacktestRun, BacktestTrade, Underlying
from app.services import history_service
from app.strategies.builder import StrategyLegSpec

SIGNAL_METRIC_NAMES = {"CALENDAR": "calendar_spread", "FORWARD_VOL": "forward_vol"}


class BacktestError(Exception):
    pass


async def _get_signal_series(
    session: AsyncSession, underlying_id: int, signal_type: str, bucket: str,
) -> tuple[list[dt.date], list[float]]:
    """Returns (dates, values_in_vol_points) for the requested signal, sorted chronologically."""
    if signal_type == "IV_RV":
        dates, iv_hist, rv_hist = await history_service.get_aligned_iv_rv_series_with_dates(session, underlying_id, bucket)
        values = [iv - rv for iv, rv in zip(iv_hist, rv_hist)]
    elif signal_type in ("CALENDAR", "FORWARD_VOL"):
        rows = await history_service.get_metric_history_with_timestamps(session, underlying_id, SIGNAL_METRIC_NAMES[signal_type], bucket)
        dates = [ts.date() for ts, _ in rows]
        values = [v for _, v in rows]
    elif signal_type in ("SKEW", "RR", "BF"):
        try:
            tenor_label, delta = bucket.split(":")
        except ValueError:
            raise BacktestError(f"bucket for {signal_type} must be 'TENOR:DELTA', e.g. '1M:25'")
        metric_prefix = {"SKEW": "skew", "RR": "rr", "BF": "bf"}[signal_type]
        rows = await history_service.get_metric_history_with_timestamps(session, underlying_id, f"{metric_prefix}_{delta}", tenor_label)
        dates = [ts.date() for ts, _ in rows]
        values = [v for _, v in rows]
    else:
        raise BacktestError(f"Unknown signal_type '{signal_type}'")

    if not dates:
        raise BacktestError(f"No historical data for {signal_type} bucket='{bucket}'")

    values_vol_points = [v * 100 for v in values]
    return dates, values_vol_points


async def _get_regime_labels(session: AsyncSession, underlying_id: int, dates: list[dt.date], settings) -> list[str]:
    hv_rows = await history_service.get_hv_series(session, underlying_id, 20, "CLOSE_CLOSE")
    hv_by_date = {ts.date(): v for ts, v in hv_rows if v is not None}
    ordered_dates = sorted(hv_by_date)
    ordered_values = [hv_by_date[d] for d in ordered_dates]

    regime_by_date: dict[dt.date, str] = {}
    for i, d in enumerate(ordered_dates):
        history = ordered_values[:i]
        if len(history) < 30:
            regime_by_date[d] = "UNKNOWN"
        else:
            regime_by_date[d] = classify_regime(
                ordered_values[i], history, settings.regime_low_percentile,
                settings.regime_high_percentile, settings.regime_extreme_percentile,
            ).regime
    return [regime_by_date.get(d, "UNKNOWN") for d in dates]


async def run_and_persist_backtest(
    session: AsyncSession, symbol: str, signal_type: str, bucket: str,
    entry_zscore: float, exit_zscore: float, max_holding_days: int,
    rolling_window_days: int, transaction_cost_vol_points: float, settings,
) -> BacktestRun:
    underlying = (await session.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if underlying is None:
        raise BacktestError(f"Unknown symbol '{symbol}'")

    dates, values = await _get_signal_series(session, underlying.id, signal_type, bucket)
    regimes = await _get_regime_labels(session, underlying.id, dates, settings)

    trades: list[Trade] = run_backtest(
        dates, values, entry_zscore, exit_zscore, max_holding_days,
        rolling_window_days, transaction_cost_vol_points, regimes,
    )
    summary = compute_summary(trades)
    breakdown = regime_breakdown(trades)

    run = BacktestRun(
        underlying_id=underlying.id, signal_type=signal_type, bucket=bucket,
        params={
            "entry_zscore": entry_zscore, "exit_zscore": exit_zscore, "max_holding_days": max_holding_days,
            "rolling_window_days": rolling_window_days, "transaction_cost_vol_points": transaction_cost_vol_points,
        },
        summary=summary, regime_breakdown=breakdown,
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(run)
    await session.flush()

    for t in trades:
        session.add(BacktestTrade(
            run_id=run.id, entry_date=t.entry_date, exit_date=t.exit_date, direction=t.direction,
            entry_value=t.entry_value, exit_value=t.exit_value, entry_zscore=t.entry_zscore,
            exit_zscore=t.exit_zscore, holding_days=t.holding_days, gross_pnl=t.gross_pnl,
            transaction_cost=t.transaction_cost, net_pnl=t.net_pnl, regime_at_entry=t.regime_at_entry,
        ))
    await session.commit()
    await session.refresh(run)
    return run


async def run_and_persist_chain_backtest(
    session: AsyncSession, symbol: str, signal_type: str, bucket: str, leg_specs: list[StrategyLegSpec],
    entry_zscore: float, exit_zscore: float, max_holding_days: int, rolling_window_days: int, settings,
) -> BacktestRun:
    """
    Same walk-forward entry/exit timing as run_and_persist_backtest (reuses
    find_trade_windows), but marks P&L using real historical option prices
    for a user-specified multi-leg strategy instead of a scalar metric
    delta — see app/backtesting/chain_replay.py.
    """
    underlying = (await session.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if underlying is None:
        raise BacktestError(f"Unknown symbol '{symbol}'")

    dates, values = await _get_signal_series(session, underlying.id, signal_type, bucket)
    regimes = await _get_regime_labels(session, underlying.id, dates, settings)
    regime_by_date = dict(zip(dates, regimes))

    windows = find_trade_windows(dates, values, entry_zscore, exit_zscore, max_holding_days, rolling_window_days)
    trades = await replay_strategy_trades(
        session, underlying.id, underlying.lot_size, leg_specs, windows, regime_by_date, settings,
    )
    summary = compute_summary(trades)
    breakdown = regime_breakdown(trades)

    run = BacktestRun(
        underlying_id=underlying.id, signal_type=signal_type, bucket=bucket, replay_mode="CHAIN",
        params={
            "entry_zscore": entry_zscore, "exit_zscore": exit_zscore, "max_holding_days": max_holding_days,
            "rolling_window_days": rolling_window_days,
            "legs": [
                {"option_type": s.option_type, "target_abs_delta": s.target_abs_delta, "action": s.action, "quantity": s.quantity}
                for s in leg_specs
            ],
        },
        summary=summary, regime_breakdown=breakdown,
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(run)
    await session.flush()

    for t in trades:
        session.add(BacktestTrade(
            run_id=run.id, entry_date=t.entry_date, exit_date=t.exit_date, direction=t.direction,
            entry_value=t.entry_value, exit_value=t.exit_value, entry_zscore=t.entry_zscore,
            exit_zscore=t.exit_zscore, holding_days=t.holding_days, gross_pnl=t.gross_pnl,
            transaction_cost=t.transaction_cost, net_pnl=t.net_pnl, regime_at_entry=t.regime_at_entry,
            legs=t.legs,
        ))
    await session.commit()
    await session.refresh(run)
    return run
