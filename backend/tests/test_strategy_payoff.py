from app.strategies.payoff import PayoffLeg, default_spot_grid, find_breakevens, payoff_curve, risk_reward_bounds


def test_long_call_max_risk_is_premium_paid_and_reward_undefined():
    legs = [PayoffLeg(strike=100.0, option_type="CALL", action="BUY", entry_price=5.0, quantity=1)]
    grid = default_spot_grid(100.0)
    curve = payoff_curve(legs, grid)
    bounds = risk_reward_bounds(legs, curve)
    assert bounds["undefined_reward"] is True
    assert bounds["max_reward"] is None
    assert bounds["undefined_risk"] is False
    assert abs(bounds["max_risk"] - 5.0) < 1e-6


def test_short_call_max_reward_is_premium_and_risk_undefined():
    legs = [PayoffLeg(strike=100.0, option_type="CALL", action="SELL", entry_price=5.0, quantity=1)]
    grid = default_spot_grid(100.0)
    curve = payoff_curve(legs, grid)
    bounds = risk_reward_bounds(legs, curve)
    assert bounds["undefined_risk"] is True
    assert bounds["max_risk"] is None
    assert abs(bounds["max_reward"] - 5.0) < 1e-6


def test_long_straddle_breakevens_bracket_strike_by_total_premium():
    call = PayoffLeg(strike=100.0, option_type="CALL", action="BUY", entry_price=4.0, quantity=1)
    put = PayoffLeg(strike=100.0, option_type="PUT", action="BUY", entry_price=3.0, quantity=1)
    grid = default_spot_grid(100.0, n=2001, lower_mult=0.5, upper_mult=1.5)
    curve = payoff_curve([call, put], grid)
    breakevens = sorted(find_breakevens(curve))
    assert len(breakevens) == 2
    assert abs(breakevens[0] - 93.0) < 0.1   # 100 - (4+3)
    assert abs(breakevens[1] - 107.0) < 0.1  # 100 + (4+3)


def test_long_straddle_has_bounded_risk_not_undefined():
    # Regression test: a long put's payoff keeps changing linearly with spot
    # all the way down to spot=0 (where it flattens), so a numerical
    # edge-slope test on a finite grid can wrongly call this "undefined" if
    # the grid's lower bound isn't close enough to zero. Boundedness must be
    # decided from the leg composition (no net call exposure here), not from
    # a finite grid's edge slope.
    call = PayoffLeg(strike=100.0, option_type="CALL", action="BUY", entry_price=4.0, quantity=1)
    put = PayoffLeg(strike=100.0, option_type="PUT", action="BUY", entry_price=3.0, quantity=1)
    grid = default_spot_grid(100.0, n=161, lower_mult=0.2, upper_mult=2.0)  # deliberately doesn't reach near 0
    curve = payoff_curve([call, put], grid)
    bounds = risk_reward_bounds([call, put], curve)
    assert bounds["undefined_risk"] is False
    assert bounds["undefined_reward"] is True  # long call -> genuinely unbounded upside
    assert abs(bounds["max_risk"] - 7.0) < 0.2  # total premium paid (coarse grid -> loose tolerance)


def test_bull_call_spread_is_fully_defined_risk_and_reward():
    long_leg = PayoffLeg(strike=100.0, option_type="CALL", action="BUY", entry_price=6.0, quantity=1)
    short_leg = PayoffLeg(strike=110.0, option_type="CALL", action="SELL", entry_price=2.0, quantity=1)
    grid = default_spot_grid(100.0)
    curve = payoff_curve([long_leg, short_leg], grid)
    bounds = risk_reward_bounds([long_leg, short_leg], curve)
    assert bounds["undefined_risk"] is False
    assert bounds["undefined_reward"] is False
    # max risk = net debit paid (6-2=4), max reward = width - debit (10-4=6)
    assert abs(bounds["max_risk"] - 4.0) < 1e-6
    assert abs(bounds["max_reward"] - 6.0) < 1e-6


def test_short_put_bounded_risk_since_spot_floor_is_zero():
    leg = PayoffLeg(strike=100.0, option_type="PUT", action="SELL", entry_price=5.0, quantity=1)
    grid = default_spot_grid(100.0, lower_mult=0.01, upper_mult=2.0)
    curve = payoff_curve([leg], grid)
    bounds = risk_reward_bounds([leg], curve)
    assert bounds["undefined_risk"] is False
    assert abs(bounds["max_risk"] - (100.0 - 5.0)) < 1.5  # grid-resolution tolerance near the spot=0 edge


def test_iron_condor_fully_hedged_calls_is_bounded():
    legs = [
        PayoffLeg(strike=120.0, option_type="CALL", action="SELL", entry_price=2.0, quantity=1),
        PayoffLeg(strike=130.0, option_type="CALL", action="BUY", entry_price=0.5, quantity=1),
        PayoffLeg(strike=80.0, option_type="PUT", action="SELL", entry_price=2.0, quantity=1),
        PayoffLeg(strike=70.0, option_type="PUT", action="BUY", entry_price=0.5, quantity=1),
    ]
    grid = default_spot_grid(100.0)
    curve = payoff_curve(legs, grid)
    bounds = risk_reward_bounds(legs, curve)
    assert bounds["undefined_risk"] is False
    assert bounds["undefined_reward"] is False
