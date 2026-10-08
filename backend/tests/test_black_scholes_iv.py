import math

from app.analytics.black_scholes import BSInputs, delta, gamma, price, put_call_parity_deviation, rho, theta, vega


def _inputs(option_type):
    return BSInputs(spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.01, sigma=0.20, option_type=option_type)


def test_put_call_parity_holds_for_bs_prices():
    call_inputs = _inputs("CALL")
    put_inputs = _inputs("PUT")
    call_price = price(call_inputs)
    put_price = price(put_inputs)
    deviation = put_call_parity_deviation(
        call_price, put_price, spot=100.0, strike=100.0, t=0.5, r=0.06, q=0.01
    )
    assert abs(deviation) < 1e-8


def test_delta_call_minus_put_equals_disc_dividend():
    call_inputs = _inputs("CALL")
    put_inputs = _inputs("PUT")
    lhs = delta(call_inputs) - delta(put_inputs)
    rhs = math.exp(-0.01 * 0.5)
    assert abs(lhs - rhs) < 1e-8


def test_gamma_vega_same_for_call_and_put():
    call_inputs = _inputs("CALL")
    put_inputs = _inputs("PUT")
    assert abs(gamma(call_inputs) - gamma(put_inputs)) < 1e-10
    assert abs(vega(call_inputs) - vega(put_inputs)) < 1e-10


def test_prices_positive_and_call_gt_intrinsic_for_atm():
    call_inputs = _inputs("CALL")
    p = price(call_inputs)
    assert p > 0
    # ATM call must be worth more than its (zero) intrinsic value given positive time value
    assert p > 0.0


def test_deep_itm_call_delta_near_one():
    inputs = BSInputs(spot=200.0, strike=100.0, time_to_expiry=0.25, rate=0.06, dividend_yield=0.0, sigma=0.2, option_type="CALL")
    assert delta(inputs) > 0.95


def test_deep_otm_put_delta_near_zero():
    inputs = BSInputs(spot=200.0, strike=100.0, time_to_expiry=0.25, rate=0.06, dividend_yield=0.0, sigma=0.2, option_type="PUT")
    assert abs(delta(inputs)) < 0.05


def test_rho_and_theta_are_finite():
    inputs = _inputs("CALL")
    assert math.isfinite(rho(inputs))
    assert math.isfinite(theta(inputs))
