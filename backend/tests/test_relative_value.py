from app.analytics.fair_value import historical_mean_fair_value, iv_rv_fair_spread, iv_rv_regression_fair_value
from app.analytics.relative_value import evaluate_relative_value


def test_historical_mean_fair_value_matches_mean():
    history = [10.0, 12.0, 14.0, 16.0, 18.0]
    assert historical_mean_fair_value(history) == 14.0


def test_historical_mean_fair_value_none_when_insufficient_history():
    assert historical_mean_fair_value([1.0, 2.0]) is None


def test_iv_rv_regression_recovers_known_linear_relationship():
    rv_history = [0.10 + 0.001 * i for i in range(50)]
    iv_history = [0.02 + 1.1 * rv for rv in rv_history]  # IV = 0.02 + 1.1*RV, no noise
    reg = iv_rv_regression_fair_value(rv_history, iv_history, current_rv=0.15)
    assert reg is not None
    assert abs(reg.slope - 1.1) < 1e-6
    assert abs(reg.intercept - 0.02) < 1e-6
    assert reg.r_squared > 0.99


def test_iv_rv_fair_spread_falls_back_to_historical_mean_with_flat_relationship():
    rv_history = [0.15] * 30  # no variance -> regression can't fit
    iv_history = [0.18 + 0.01 * ((-1) ** i) for i in range(30)]
    fair, model = iv_rv_fair_spread(rv_history, iv_history, current_rv=0.15)
    assert model == "historical_mean"
    assert fair is not None


def test_evaluate_relative_value_flags_rich_when_far_above_history():
    history = [0.0, 0.01, -0.01, 0.02, -0.02, 0.01, 0.0, 0.015, -0.005, 0.005]
    signal = evaluate_relative_value("test_metric", observed=0.5, history_series=history, fair_value=0.0, fair_value_model="historical_mean", zscore_threshold=2.0)
    assert signal.signal == "RICH"
    assert signal.deviation == 0.5
    assert signal.history.zscore > 2.0


def test_evaluate_relative_value_flags_cheap_when_far_below_history():
    history = [0.0, 0.01, -0.01, 0.02, -0.02, 0.01, 0.0, 0.015, -0.005, 0.005]
    signal = evaluate_relative_value("test_metric", observed=-0.5, history_series=history, fair_value=None, fair_value_model=None, zscore_threshold=2.0)
    assert signal.signal == "CHEAP"


def test_evaluate_relative_value_neutral_within_threshold():
    history = list(range(1, 101))
    signal = evaluate_relative_value("test_metric", observed=52, history_series=history, fair_value=None, fair_value_model=None, zscore_threshold=2.0)
    assert signal.signal == "NEUTRAL"


def test_evaluate_relative_value_insufficient_data():
    signal = evaluate_relative_value("test_metric", observed=1.0, history_series=[1.0], fair_value=None, fair_value_model=None, zscore_threshold=2.0)
    assert signal.signal == "INSUFFICIENT_DATA"
    assert signal.history is None
