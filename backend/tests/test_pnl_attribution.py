from app.simulation.pnl_attribution import attribute_pnl


def _greeks(**overrides):
    base = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    base.update(overrides)
    return base


def test_zero_moves_only_carry_and_theta_survive():
    greeks = _greeks(delta=10.0, gamma=1.0, theta=-5.0, vega=100.0)
    result = attribute_pnl(greeks, net_premium=1000.0, d_spot=0.0, d_sigma_vol_points=0.0, dt_days=1.0, rate=0.06)
    assert result.spot_pnl == 0.0
    assert result.gamma_pnl == 0.0
    assert result.vega_pnl == 0.0
    assert result.vanna_pnl == 0.0
    assert result.volga_pnl == 0.0
    assert result.theta_pnl == -5.0
    assert abs(result.carry_pnl - (-0.06 * 1000.0 / 365.0)) < 1e-9


def test_gamma_pnl_positive_regardless_of_spot_direction_for_long_gamma():
    greeks = _greeks(gamma=2.0)
    up = attribute_pnl(greeks, 0.0, d_spot=5.0, d_sigma_vol_points=0.0, dt_days=0.0, rate=0.0)
    down = attribute_pnl(greeks, 0.0, d_spot=-5.0, d_sigma_vol_points=0.0, dt_days=0.0, rate=0.0)
    assert up.gamma_pnl > 0
    assert down.gamma_pnl > 0
    assert abs(up.gamma_pnl - down.gamma_pnl) < 1e-9  # symmetric in |dS|


def test_spot_pnl_matches_delta_times_move():
    greeks = _greeks(delta=25.0)
    result = attribute_pnl(greeks, 0.0, d_spot=10.0, d_sigma_vol_points=0.0, dt_days=0.0, rate=0.0)
    assert abs(result.spot_pnl - 250.0) < 1e-9


def test_vega_pnl_sign_matches_vega_and_vol_move_direction():
    greeks = _greeks(vega=50.0)
    up_vol = attribute_pnl(greeks, 0.0, d_spot=0.0, d_sigma_vol_points=2.0, dt_days=0.0, rate=0.0)
    down_vol = attribute_pnl(greeks, 0.0, d_spot=0.0, d_sigma_vol_points=-2.0, dt_days=0.0, rate=0.0)
    assert up_vol.vega_pnl > 0
    assert down_vol.vega_pnl < 0
    assert abs(up_vol.vega_pnl + down_vol.vega_pnl) < 1e-9


def test_total_is_sum_of_components():
    greeks = _greeks(delta=5.0, gamma=0.5, theta=-2.0, vega=30.0, vanna=1.0, volga=2.0)
    result = attribute_pnl(greeks, net_premium=500.0, d_spot=3.0, d_sigma_vol_points=1.5, dt_days=1.0, rate=0.05)
    expected = (
        result.spot_pnl + result.gamma_pnl + result.theta_pnl + result.vega_pnl
        + result.vanna_pnl + result.volga_pnl + result.carry_pnl
    )
    assert abs(result.total - expected) < 1e-9


def test_carry_pnl_is_negative_for_positive_net_premium_and_positive_rate():
    result = attribute_pnl(_greeks(), net_premium=1000.0, d_spot=0.0, d_sigma_vol_points=0.0, dt_days=10.0, rate=0.06)
    assert result.carry_pnl < 0  # financing cost of a debit position


def test_carry_pnl_is_positive_for_credit_position():
    result = attribute_pnl(_greeks(), net_premium=-1000.0, d_spot=0.0, d_sigma_vol_points=0.0, dt_days=10.0, rate=0.06)
    assert result.carry_pnl > 0  # earning financing on a net credit received
