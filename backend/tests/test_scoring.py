from app.opportunities.scoring import model_confidence_score


def test_model_confidence_saturates_at_the_full_target_sample():
    assert model_confidence_score(1260, 0, "GOOD", target_sample=1260) == 100.0
    assert model_confidence_score(5000, 0, "GOOD", target_sample=1260) == 100.0  # more than the target still caps at 100


def test_model_confidence_scales_proportionally_below_target():
    # 970/1260 of the full configured lookback -> ~77, not saturated to 100
    result = model_confidence_score(970, 0, "GOOD", target_sample=1260)
    assert 76.0 < result < 78.0


def test_model_confidence_does_not_saturate_just_past_the_old_hardcoded_floor():
    # Regression test: sample sizes around the old 120-sample floor used to
    # saturate to 100 outright once history was deep. Against the real
    # target (percentile_lookback_days), the same sample size should score
    # far below 100.
    result = model_confidence_score(150, 0, "GOOD", target_sample=1260)
    assert result < 15.0


def test_model_confidence_penalizes_failed_no_arbitrage_flags():
    clean = model_confidence_score(1260, 0, "GOOD", target_sample=1260)
    flagged = model_confidence_score(1260, 2, "GOOD", target_sample=1260)
    assert flagged == clean - 30


def test_model_confidence_penalizes_non_good_data_quality():
    clean = model_confidence_score(1260, 0, "GOOD", target_sample=1260)
    degraded = model_confidence_score(1260, 0, "MISSING_IV", target_sample=1260)
    assert degraded == clean - 20


def test_model_confidence_is_clamped_to_zero_not_negative():
    result = model_confidence_score(10, 5, "MISSING_IV", target_sample=1260)
    assert result == 0.0
