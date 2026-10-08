import numpy as np
import pandas as pd

from app.analytics.realized_vol import (
    close_to_close_vol,
    garman_klass_vol,
    historical_volatility_suite,
    parkinson_vol,
    rogers_satchell_vol,
    yang_zhang_vol,
)


def _make_gbm_ohlc(n=300, daily_vol=0.02, seed=42):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, daily_vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[100.0], close[:-1]])
    # Intraday range consistent with the same daily vol, so range-based
    # estimators should also recover ~daily_vol annualized.
    intraday_noise = rng.uniform(0.001, daily_vol * 0.8, n)
    high = np.maximum(open_, close) + np.abs(intraday_noise) * close
    low = np.minimum(open_, close) - np.abs(intraday_noise) * close
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def test_close_to_close_recovers_known_annualized_vol():
    daily_vol = 0.02
    df = _make_gbm_ohlc(n=500, daily_vol=daily_vol, seed=1)
    hv = close_to_close_vol(df["close"], window=252, annualization=252)
    expected = daily_vol * (252 ** 0.5)
    assert hv is not None
    assert abs(hv - expected) / expected < 0.15  # within 15% given sampling noise


def test_range_based_estimators_return_positive_finite_values():
    df = _make_gbm_ohlc(n=100, seed=2)
    for fn in (parkinson_vol, garman_klass_vol, rogers_satchell_vol, yang_zhang_vol):
        v = fn(df, window=30, annualization=252)
        assert v is not None
        assert v > 0


def test_insufficient_history_returns_none():
    df = _make_gbm_ohlc(n=10, seed=3)
    assert close_to_close_vol(df["close"], window=252, annualization=252) is None
    assert parkinson_vol(df, window=252, annualization=252) is None


def test_hv_suite_returns_all_configured_windows():
    df = _make_gbm_ohlc(n=300, seed=4)
    windows = [5, 10, 20, 30, 60, 90, 252]
    suite = historical_volatility_suite(df, windows, annualization=252, estimator="CLOSE_CLOSE")
    assert set(suite.keys()) == {f"hv_{w}" for w in windows}
    assert all(v is not None and v > 0 for v in suite.values())
