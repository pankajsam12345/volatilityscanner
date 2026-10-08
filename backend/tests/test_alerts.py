import pytest

from app.alerts.engine import evaluate_condition, should_fire


def test_evaluate_condition_greater_than():
    assert evaluate_condition(3.0, ">", 2.0)
    assert not evaluate_condition(1.0, ">", 2.0)


def test_evaluate_condition_less_than():
    assert evaluate_condition(1.0, "<", 2.0)
    assert not evaluate_condition(3.0, "<", 2.0)


def test_evaluate_condition_unknown_raises():
    with pytest.raises(ValueError):
        evaluate_condition(1.0, "==", 2.0)


def test_should_fire_transitions_false_to_true():
    met, fire = should_fire(3.0, ">", 2.0, currently_met=False)
    assert met is True
    assert fire is True


def test_should_fire_does_not_repeat_while_still_met():
    met, fire = should_fire(3.0, ">", 2.0, currently_met=True)
    assert met is True
    assert fire is False


def test_should_fire_resets_when_condition_no_longer_met():
    met, fire = should_fire(1.0, ">", 2.0, currently_met=True)
    assert met is False
    assert fire is False


def test_should_fire_none_observed_keeps_previous_state():
    met, fire = should_fire(None, ">", 2.0, currently_met=True)
    assert met is True
    assert fire is False
