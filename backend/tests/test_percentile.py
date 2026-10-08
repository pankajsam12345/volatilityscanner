from app.analytics.stats import distribution_context, percentile_rank


def test_percentile_rank_of_max_is_100():
    history = [1, 2, 3, 4, 5]
    assert percentile_rank(5, history) == 100.0


def test_percentile_rank_of_min_is_20_for_five_points():
    history = [1, 2, 3, 4, 5]
    assert percentile_rank(1, history) == 20.0


def test_percentile_rank_matches_spec_example():
    # §18: ATM IV current 21.4%, 5Y percentile 87% — construct a history where
    # 87% of observations sit at or below the current value.
    history = list(range(1, 101))  # 1..100
    current = 87
    assert percentile_rank(current, history) == 87.0


def test_distribution_context_matches_manual_stats():
    history = [10.0, 12.0, 14.0, 16.0, 18.0]
    ctx = distribution_context(14.0, history)
    assert ctx is not None
    assert ctx.mean == 14.0
    assert ctx.median == 14.0
    assert ctx.sample_size == 5


def test_empty_history_returns_none():
    assert percentile_rank(5, []) is None
    assert distribution_context(5, []) is None
