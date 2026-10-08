import datetime as dt

import numpy as np

from app.backtesting.engine import Trade, run_backtest
from app.backtesting.stats import compute_summary, equity_curve, regime_breakdown


def _dates(n, start=dt.date(2025, 1, 1)):
    return [start + dt.timedelta(days=i) for i in range(n)]


def test_run_backtest_opens_short_on_rich_extreme_and_exits_on_reversion():
    # 60 deterministic-stable days around 0, then a spike to 10 (extreme RICH),
    # then reverts back to 0. Tiny alternating jitter never crosses |z|>=2 on
    # its own, so the only genuine extreme is the designed spike.
    stable = [0.1 if i % 2 == 0 else -0.1 for i in range(60)]
    values = stable + [10.0, 8.0, 4.0, 1.0, 0.2]
    dates = _dates(len(values))

    trades = run_backtest(
        dates, values, entry_zscore=2.0, exit_zscore=0.5, max_holding_days=20,
        rolling_window_days=60, transaction_cost_vol_points=0.1, min_window_samples=30,
    )
    assert len(trades) == 1
    first = trades[0]
    assert first.direction == "SHORT"  # entered on a RICH (high z-score) extreme
    assert first.gross_pnl > 0  # metric fell back down after entry -> short vol profits


def test_run_backtest_opens_long_on_cheap_extreme():
    # Deterministic tiny alternating jitter (never crosses |z|>=2 on its own) so the
    # only genuine extreme is the designed spike — avoids flaky spurious entries
    # from random noise occasionally crossing the threshold early.
    stable = [0.1 if i % 2 == 0 else -0.1 for i in range(60)]
    values = stable + [-10.0, -8.0, -4.0, -1.0, -0.2]
    dates = _dates(len(values))

    trades = run_backtest(
        dates, values, entry_zscore=2.0, exit_zscore=0.5, max_holding_days=20,
        rolling_window_days=60, transaction_cost_vol_points=0.1, min_window_samples=30,
    )
    assert len(trades) == 1
    assert trades[0].direction == "LONG"
    assert trades[0].gross_pnl > 0  # metric rose back up -> long profits


def test_max_holding_days_forces_exit():
    stable = [0.1 if i % 2 == 0 else -0.1 for i in range(60)]
    # spike stays elevated (no reversion within window) to force a max-holding exit
    values = stable + [10.0] * 10
    dates = _dates(len(values))

    trades = run_backtest(
        dates, values, entry_zscore=2.0, exit_zscore=0.5, max_holding_days=5,
        rolling_window_days=60, transaction_cost_vol_points=0.1, min_window_samples=30,
    )
    assert len(trades) >= 1
    assert trades[0].holding_days <= 5


def test_no_trade_when_never_extreme():
    rng = np.random.default_rng(3)
    values = list(rng.normal(0, 0.3, 100))
    dates = _dates(len(values))
    trades = run_backtest(
        dates, values, entry_zscore=5.0, exit_zscore=0.5, max_holding_days=20,
        rolling_window_days=60, transaction_cost_vol_points=0.1, min_window_samples=30,
    )
    assert trades == []


def test_open_position_is_marked_to_market_at_end():
    stable = [0.1 if i % 2 == 0 else -0.1 for i in range(60)]
    values = stable + [10.0, 9.5, 9.0]  # spikes and stays elevated right to the end
    dates = _dates(len(values))
    trades = run_backtest(
        dates, values, entry_zscore=2.0, exit_zscore=0.5, max_holding_days=100,
        rolling_window_days=60, transaction_cost_vol_points=0.1, min_window_samples=30,
    )
    assert len(trades) == 1
    assert trades[0].exit_date == dates[-1]


def test_dates_values_length_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        run_backtest([dt.date(2025, 1, 1)], [1.0, 2.0], 2.0, 0.5, 20, 60, 0.1)


def _hand_built_trades():
    d = _dates(6)
    return [
        Trade(d[0], d[1], "SHORT", 5.0, 1.0, 3.0, 0.2, 1, 4.0, 0.5, 3.5, "HIGH"),
        Trade(d[2], d[3], "LONG", -5.0, -1.0, -3.0, -0.2, 1, 4.0, 0.5, 3.5, "LOW"),
        Trade(d[4], d[5], "SHORT", 3.0, 5.0, 2.5, 2.0, 1, -2.0, 0.5, -2.5, "HIGH"),
    ]


def test_compute_summary_basic_stats():
    trades = _hand_built_trades()
    summary = compute_summary(trades)
    assert summary["num_trades"] == 3
    assert abs(summary["win_rate"] - (2 / 3 * 100)) < 1e-6
    assert abs(summary["total_pnl"] - (3.5 + 3.5 - 2.5)) < 1e-6
    assert summary["profit_factor"] is not None
    assert summary["max_drawdown"] >= 0


def test_compute_summary_empty_trades():
    summary = compute_summary([])
    assert summary["num_trades"] == 0
    assert summary["total_pnl"] == 0.0
    assert summary["win_rate"] is None


def test_equity_curve_is_cumulative():
    trades = _hand_built_trades()
    curve = equity_curve(trades)
    assert len(curve) == 3
    assert abs(curve[-1]["cumulative_pnl"] - (3.5 + 3.5 - 2.5)) < 1e-6
    assert curve[0]["cumulative_pnl"] < curve[1]["cumulative_pnl"]


def test_regime_breakdown_groups_by_entry_regime():
    trades = _hand_built_trades()
    breakdown = regime_breakdown(trades)
    assert set(breakdown.keys()) == {"HIGH", "LOW"}
    assert breakdown["HIGH"]["num_trades"] == 2
    assert breakdown["LOW"]["num_trades"] == 1
