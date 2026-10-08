from app.backtesting.chain_replay import _legs_for_direction
from app.strategies.builder import StrategyLegSpec


def test_short_direction_keeps_legs_unchanged():
    legs = [
        StrategyLegSpec("CALL", 0.5, "SELL", 1),
        StrategyLegSpec("PUT", 0.5, "SELL", 1),
    ]
    result = _legs_for_direction(legs, "SHORT")
    assert result == legs


def test_long_direction_flips_every_leg_action():
    legs = [
        StrategyLegSpec("CALL", 0.5, "SELL", 1),
        StrategyLegSpec("PUT", 0.25, "SELL", 2),
    ]
    result = _legs_for_direction(legs, "LONG")
    assert [l.action for l in result] == ["BUY", "BUY"]
    # strikes/quantities (expressed via option_type/target_abs_delta/quantity) are preserved
    assert [(l.option_type, l.target_abs_delta, l.quantity) for l in result] == [
        (l.option_type, l.target_abs_delta, l.quantity) for l in legs
    ]


def test_long_direction_flips_buy_legs_to_sell_too():
    legs = [StrategyLegSpec("CALL", 0.5, "BUY", 1)]
    result = _legs_for_direction(legs, "LONG")
    assert result[0].action == "SELL"
