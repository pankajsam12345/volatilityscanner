"""
Signal-level backtesting engine (§36-37): walks an already-computed
historical metric series (e.g. the IV-RV spread, a calendar spread, a
skew/RR/BF reading) day by day, using a *rolling* z-score computed only
from days strictly before the current one — walk-forward by construction,
never looking ahead. This backtests the relative-value signal's mean-
reversion (cost-adjusted), not a full historical option-chain P&L replay,
which the system was never seeded to support (see README limitations).

Units are whatever the caller passes in (the service layer converts IV-
derived metrics to vol points before calling this, matching
opportunities/strategies.py's convention, so P&L nets correctly against
transaction_cost_vol_points).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.analytics.stats import zscore


@dataclass(frozen=True)
class Trade:
    entry_date: dt.date
    exit_date: dt.date
    direction: str  # SHORT | LONG
    entry_value: float
    exit_value: float
    entry_zscore: float
    exit_zscore: float
    holding_days: int
    gross_pnl: float
    transaction_cost: float
    net_pnl: float
    regime_at_entry: str


@dataclass(frozen=True)
class TradeWindow:
    """When to trade, decided purely from the signal series — the entry/exit
    state machine shared by the scalar signal backtest (run_backtest, below)
    and the chain-replay backtest (app/backtesting/chain_replay.py), which
    only differs in *how* P&L for a window gets computed (a scalar metric
    delta here vs. real leg repricing there)."""
    entry_date: dt.date
    exit_date: dt.date
    direction: str  # SHORT | LONG
    entry_zscore: float
    exit_zscore: float


def find_trade_windows(
    dates: list[dt.date],
    values: list[float],
    entry_zscore: float,
    exit_zscore: float,
    max_holding_days: int,
    rolling_window_days: int,
    min_window_samples: int = 30,
) -> list[TradeWindow]:
    if len(dates) != len(values):
        raise ValueError("dates and values must be the same length")

    windows: list[TradeWindow] = []
    position: dict | None = None

    for i in range(len(values)):
        window = values[max(0, i - rolling_window_days):i]
        if len(window) < min_window_samples:
            continue
        z = zscore(values[i], window)
        if z is None:
            continue

        if position is None:
            if z >= entry_zscore:
                position = {"direction": "SHORT", "entry_idx": i, "entry_zscore": z}
            elif z <= -entry_zscore:
                position = {"direction": "LONG", "entry_idx": i, "entry_zscore": z}
            continue

        holding_days = i - position["entry_idx"]
        should_exit = (
            (position["direction"] == "SHORT" and z <= exit_zscore)
            or (position["direction"] == "LONG" and z >= -exit_zscore)
            or holding_days >= max_holding_days
        )
        if should_exit:
            windows.append(TradeWindow(
                entry_date=dates[position["entry_idx"]], exit_date=dates[i], direction=position["direction"],
                entry_zscore=position["entry_zscore"], exit_zscore=z,
            ))
            position = None

    # Mark-to-market any still-open position at the last available day.
    if position is not None:
        last_idx = len(values) - 1
        last_window = values[max(0, last_idx - rolling_window_days):last_idx]
        z = zscore(values[last_idx], last_window) if len(last_window) >= min_window_samples else position["entry_zscore"]
        windows.append(TradeWindow(
            entry_date=dates[position["entry_idx"]], exit_date=dates[last_idx], direction=position["direction"],
            entry_zscore=position["entry_zscore"], exit_zscore=z,
        ))

    return windows


def run_backtest(
    dates: list[dt.date],
    values: list[float],
    entry_zscore: float,
    exit_zscore: float,
    max_holding_days: int,
    rolling_window_days: int,
    transaction_cost_vol_points: float,
    regime_labels: list[str] | None = None,
    min_window_samples: int = 30,
) -> list[Trade]:
    regimes = regime_labels or ["UNKNOWN"] * len(values)
    date_index = {d: i for i, d in enumerate(dates)}
    windows = find_trade_windows(dates, values, entry_zscore, exit_zscore, max_holding_days, rolling_window_days, min_window_samples)

    trades: list[Trade] = []
    for w in windows:
        entry_idx, exit_idx = date_index[w.entry_date], date_index[w.exit_date]
        entry_value, exit_value = values[entry_idx], values[exit_idx]
        gross_pnl = (entry_value - exit_value) if w.direction == "SHORT" else (exit_value - entry_value)
        net_pnl = gross_pnl - transaction_cost_vol_points
        trades.append(Trade(
            entry_date=w.entry_date, exit_date=w.exit_date, direction=w.direction,
            entry_value=entry_value, exit_value=exit_value,
            entry_zscore=w.entry_zscore, exit_zscore=w.exit_zscore,
            holding_days=exit_idx - entry_idx, gross_pnl=gross_pnl,
            transaction_cost=transaction_cost_vol_points, net_pnl=net_pnl,
            regime_at_entry=regimes[entry_idx],
        ))
    return trades
