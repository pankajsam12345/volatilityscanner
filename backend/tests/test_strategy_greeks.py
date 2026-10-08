from app.analytics.black_scholes import BSInputs, delta, gamma, theta, vega
from app.opportunities.greeks_aggregator import aggregate_strategy_greeks


def _greeks_dict(inputs: BSInputs) -> dict:
    return {"delta": delta(inputs), "gamma": gamma(inputs), "vega": vega(inputs), "theta": theta(inputs)}


def test_long_straddle_delta_near_zero_atm():
    # Zero rate/dividend so there's no forward drift pushing d1 away from 0 —
    # otherwise delta_call + delta_put = disc_q*(2N(d1)-1) isn't ~0 even ATM.
    call_inputs = BSInputs(100.0, 100.0, 0.5, 0.0, 0.0, 0.2, "CALL")
    put_inputs = BSInputs(100.0, 100.0, 0.5, 0.0, 0.0, 0.2, "PUT")
    totals = aggregate_strategy_greeks(["BUY", "BUY"], [_greeks_dict(call_inputs), _greeks_dict(put_inputs)])
    assert abs(totals["delta"]) < 0.1  # near-ATM straddle is close to delta-neutral
    assert totals["vega"] > 0  # long vega
    assert totals["gamma"] > 0


def test_short_straddle_flips_sign_of_long_straddle():
    call_inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "CALL")
    put_inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "PUT")
    long_totals = aggregate_strategy_greeks(["BUY", "BUY"], [_greeks_dict(call_inputs), _greeks_dict(put_inputs)])
    short_totals = aggregate_strategy_greeks(["SELL", "SELL"], [_greeks_dict(call_inputs), _greeks_dict(put_inputs)])
    for key in ("delta", "gamma", "vega", "theta"):
        assert abs(long_totals[key] + short_totals[key]) < 1e-9


def test_vega_doubles_for_two_identical_long_legs():
    inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "CALL")
    single = vega(inputs)
    totals = aggregate_strategy_greeks(["BUY", "BUY"], [_greeks_dict(inputs), _greeks_dict(inputs)])
    assert abs(totals["vega"] - 2 * single) < 1e-9


def test_quantities_scale_greeks():
    inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "CALL")
    totals = aggregate_strategy_greeks(["BUY"], [_greeks_dict(inputs)], leg_quantities=[3])
    assert abs(totals["vega"] - 3 * vega(inputs)) < 1e-9


def test_missing_greek_key_defaults_to_zero_contribution():
    totals = aggregate_strategy_greeks(["BUY"], [{"delta": 0.5}])
    assert totals["delta"] == 0.5
    assert totals["vega"] == 0.0
