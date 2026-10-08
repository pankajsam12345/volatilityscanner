"""
Realized / historical volatility estimators (§7).

All estimators take a pandas DataFrame indexed chronologically (oldest
first) with at least a `close` column; the range-based estimators also need
`open`, `high`, `low`. Each estimator returns an *annualized* volatility
(e.g. 0.184 for 18.4%) for the given trailing window using the most recent
`window` observations. `annualization` is configurable (252 trading days or
365 calendar days per spec §7/§45).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LN2 = math.log(2)


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def close_to_close_vol(close: pd.Series, window: int, annualization: int = 252) -> float | None:
    rets = log_returns(close)
    if len(rets) < window:
        return None
    tail = rets.iloc[-window:]
    return float(tail.std(ddof=1) * math.sqrt(annualization))


def parkinson_vol(df: pd.DataFrame, window: int, annualization: int = 252) -> float | None:
    if len(df) < window:
        return None
    tail = df.iloc[-window:]
    hl = np.log(tail["high"] / tail["low"]) ** 2
    daily_var = hl.mean() / (4 * LN2)
    return float(math.sqrt(max(daily_var, 0.0) * annualization))


def garman_klass_vol(df: pd.DataFrame, window: int, annualization: int = 252) -> float | None:
    if len(df) < window:
        return None
    tail = df.iloc[-window:]
    hl_term = 0.5 * np.log(tail["high"] / tail["low"]) ** 2
    co_term = (2 * LN2 - 1) * np.log(tail["close"] / tail["open"]) ** 2
    daily_var = (hl_term - co_term).mean()
    return float(math.sqrt(max(daily_var, 0.0) * annualization))


def rogers_satchell_vol(df: pd.DataFrame, window: int, annualization: int = 252) -> float | None:
    if len(df) < window:
        return None
    tail = df.iloc[-window:]
    term = (
        np.log(tail["high"] / tail["close"]) * np.log(tail["high"] / tail["open"])
        + np.log(tail["low"] / tail["close"]) * np.log(tail["low"] / tail["open"])
    )
    daily_var = term.mean()
    return float(math.sqrt(max(daily_var, 0.0) * annualization))


def yang_zhang_vol(df: pd.DataFrame, window: int, annualization: int = 252) -> float | None:
    if len(df) < window + 1:
        return None
    tail = df.iloc[-(window + 1):].reset_index(drop=True)
    prev_close = tail["close"].shift(1)
    overnight = np.log(tail["open"] / prev_close).dropna()
    open_close = np.log(tail["close"] / tail["open"]).iloc[1:]
    rs_term = (
        np.log(tail["high"] / tail["close"]) * np.log(tail["high"] / tail["open"])
        + np.log(tail["low"] / tail["close"]) * np.log(tail["low"] / tail["open"])
    ).iloc[1:]

    n = len(overnight)
    if n < 2:
        return None

    var_o = overnight.var(ddof=1)
    var_c = open_close.var(ddof=1)
    var_rs = rs_term.mean()

    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    daily_var = var_o + k * var_c + (1 - k) * var_rs
    return float(math.sqrt(max(daily_var, 0.0) * annualization))


def ewma_vol(close: pd.Series, lambda_: float = 0.94, annualization: int = 252, min_periods: int = 30) -> float | None:
    rets = log_returns(close)
    if len(rets) < min_periods:
        return None
    var = rets.iloc[0] ** 2
    for r in rets.iloc[1:]:
        var = lambda_ * var + (1 - lambda_) * r ** 2
    return float(math.sqrt(max(var, 0.0) * annualization))


ESTIMATORS = {
    "CLOSE_CLOSE": lambda df, w, ann: close_to_close_vol(df["close"], w, ann),
    "PARKINSON": parkinson_vol,
    "GARMAN_KLASS": garman_klass_vol,
    "ROGERS_SATCHELL": rogers_satchell_vol,
    "YANG_ZHANG": yang_zhang_vol,
}


def historical_volatility_suite(
    df: pd.DataFrame,
    windows: list[int],
    annualization: int = 252,
    estimator: str = "CLOSE_CLOSE",
) -> dict[str, float | None]:
    """Returns {"hv_5": ..., "hv_10": ..., ...} for the given estimator."""
    fn = ESTIMATORS[estimator]
    return {f"hv_{w}": fn(df, w, annualization) for w in windows}
