from app.analytics.regime import classify_regime


def test_low_regime_when_below_low_percentile():
    history = list(range(1, 101))  # 1..100
    result = classify_regime(10, history)  # 10th percentile
    assert result.regime == "LOW"


def test_normal_regime_in_middle():
    history = list(range(1, 101))
    result = classify_regime(50, history)  # 50th percentile
    assert result.regime == "NORMAL"


def test_high_regime_above_75th():
    history = list(range(1, 101))
    result = classify_regime(80, history)
    assert result.regime == "HIGH"


def test_extreme_regime_above_95th():
    history = list(range(1, 101))
    result = classify_regime(99, history)
    assert result.regime == "EXTREME"


def test_unknown_regime_with_insufficient_history():
    result = classify_regime(10, [5.0])
    assert result.regime == "UNKNOWN"
    assert result.percentile is None


def test_custom_thresholds_respected():
    history = list(range(1, 101))
    result = classify_regime(60, history, low_percentile=10, high_percentile=50, extreme_percentile=90)
    assert result.regime == "HIGH"
