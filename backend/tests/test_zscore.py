import math

from app.analytics.stats import zscore


def test_zscore_of_mean_is_zero():
    history = [10.0, 12.0, 14.0, 16.0, 18.0]  # mean=14, std=~3.16
    assert abs(zscore(14.0, history)) < 1e-9


def test_zscore_matches_manual_computation():
    history = [10.0, 12.0, 14.0, 16.0, 18.0]
    mean = sum(history) / len(history)
    std = math.sqrt(sum((x - mean) ** 2 for x in history) / (len(history) - 1))
    current = 20.0
    expected = (current - mean) / std
    assert abs(zscore(current, history) - expected) < 1e-9


def test_zscore_extreme_value_matches_spec_example_direction():
    # §19 example: calendar spread current -2.7, historical mean -0.2 -> strongly negative z-score
    history = [-0.1, -0.2, -0.3, -0.15, -0.25, -0.2, -0.18]
    z = zscore(-2.7, history)
    assert z < -2.0


def test_zscore_zero_variance_returns_zero():
    history = [5.0, 5.0, 5.0, 5.0]
    assert zscore(5.0, history) == 0.0


def test_zscore_insufficient_history_returns_none():
    assert zscore(5.0, [1.0]) is None
    assert zscore(5.0, []) is None
