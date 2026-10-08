from app.risk.portfolio_risk import aggregate_position_greeks, parametric_var, what_if_grid


def test_aggregate_position_greeks_sums_across_positions_and_legs():
    pos1_legs = [{"delta": 0.5, "vega": 10.0}, {"delta": -0.3, "vega": 8.0}]
    pos2_legs = [{"delta": 0.2, "vega": 5.0}]
    totals = aggregate_position_greeks([pos1_legs, pos2_legs], quantities=[2, 1])
    # position 1 scaled by qty=2: delta=(0.5-0.3)*2=0.4, vega=(10+8)*2=36
    # position 2 scaled by qty=1: delta=0.2, vega=5
    assert abs(totals["delta"] - 0.6) < 1e-9
    assert abs(totals["vega"] - 41.0) < 1e-9


def test_aggregate_position_greeks_handles_missing_keys():
    totals = aggregate_position_greeks([[{"delta": 1.0}]], quantities=[1])
    assert totals["delta"] == 1.0
    assert totals["gamma"] == 0.0


def test_parametric_var_zero_greeks_is_zero_risk():
    risk = parametric_var(delta=0.0, vega=0.0, spot=100.0, daily_spot_vol=0.01, daily_vol_of_vol_points=0.3)
    assert risk.daily_std == 0.0
    assert risk.var_95 == 0.0
    assert risk.cvar_95 == 0.0


def test_parametric_var_cvar_exceeds_var():
    risk = parametric_var(delta=10.0, vega=500.0, spot=100.0, daily_spot_vol=0.015, daily_vol_of_vol_points=0.3)
    assert risk.cvar_95 > risk.var_95 > 0


def test_parametric_var_scales_with_delta():
    small = parametric_var(delta=5.0, vega=0.0, spot=100.0, daily_spot_vol=0.01, daily_vol_of_vol_points=0.0)
    large = parametric_var(delta=10.0, vega=0.0, spot=100.0, daily_spot_vol=0.01, daily_vol_of_vol_points=0.0)
    assert abs(large.var_95 - 2 * small.var_95) < 1e-9


def test_what_if_grid_produces_full_cartesian_product():
    greeks = {"delta": 1.0, "gamma": 0.1, "theta": -1.0, "vega": 10.0, "vanna": 0.0, "volga": 0.0}
    cells = what_if_grid(
        greeks, net_premium=0.0, rate=0.05, reference_spot=100.0,
        spot_shocks_pct=[-0.03, 0.03], vol_shocks_pts=[-1.0, 1.0], time_shocks_days=[1, 5],
    )
    assert len(cells) == 2 * 2 * 2


def test_what_if_grid_spot_shock_direction_matches_delta_sign():
    greeks = {"delta": 10.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    cells = what_if_grid(greeks, 0.0, 0.0, 100.0, [0.03], [0.0], [0])
    assert cells[0]["pnl"] > 0  # positive delta + positive spot shock -> positive pnl
