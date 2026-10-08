"""Backtest performance statistics (§36-37) — pure functions over a trade list."""
from __future__ import annotations

import numpy as np

from app.backtesting.engine import Trade


def compute_summary(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "num_trades": 0, "win_rate": None, "avg_return": None, "median_return": None,
            "max_drawdown": None, "sharpe": None, "profit_factor": None, "tail_loss_p5": None,
            "total_pnl": 0.0,
        }

    net_pnls = np.array([t.net_pnl for t in trades])
    num_trades = len(trades)
    win_rate = float((net_pnls > 0).sum() / num_trades * 100)
    avg_return = float(net_pnls.mean())
    median_return = float(np.median(net_pnls))
    total_pnl = float(net_pnls.sum())

    equity_curve = np.cumsum(net_pnls)
    running_max = np.maximum.accumulate(equity_curve)
    drawdowns = running_max - equity_curve
    max_drawdown = float(drawdowns.max())

    std = net_pnls.std(ddof=1) if num_trades > 1 else 0.0
    avg_holding_days = float(np.mean([t.holding_days for t in trades])) or 1.0
    if std > 1e-9:
        sharpe = float(avg_return / std * np.sqrt(252.0 / avg_holding_days))
    else:
        sharpe = None

    wins = net_pnls[net_pnls > 0].sum()
    losses = net_pnls[net_pnls < 0].sum()
    profit_factor = float(wins / abs(losses)) if losses < 0 else None

    tail_loss_p5 = float(np.percentile(net_pnls, 5))

    return {
        "num_trades": num_trades, "win_rate": win_rate, "avg_return": avg_return,
        "median_return": median_return, "max_drawdown": max_drawdown, "sharpe": sharpe,
        "profit_factor": profit_factor, "tail_loss_p5": tail_loss_p5, "total_pnl": total_pnl,
    }


def equity_curve(trades: list[Trade]) -> list[dict]:
    cum = 0.0
    curve = []
    for t in trades:
        cum += t.net_pnl
        curve.append({"date": t.exit_date, "cumulative_pnl": cum})
    return curve


def regime_breakdown(trades: list[Trade]) -> dict[str, dict]:
    by_regime: dict[str, list[Trade]] = {}
    for t in trades:
        by_regime.setdefault(t.regime_at_entry, []).append(t)
    return {regime: compute_summary(regime_trades) for regime, regime_trades in by_regime.items()}
