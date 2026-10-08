from app.analytics.black_scholes import BSInputs, price
from app.analytics.no_arbitrage import (
    check_bid_ask,
    check_butterfly_convexity,
    check_calendar_variance,
    check_put_call_parity,
)
from app.analytics.term_structure import forward_vol


def test_put_call_parity_passes_for_consistent_bs_prices():
    call_inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "CALL")
    put_inputs = BSInputs(100.0, 100.0, 0.5, 0.06, 0.01, 0.2, "PUT")
    flag = check_put_call_parity(price(call_inputs), price(put_inputs), 100.0, 100.0, 0.5, 0.06, 0.01)
    assert flag.passed


def test_put_call_parity_fails_for_inconsistent_quotes():
    flag = check_put_call_parity(call_price=50.0, put_price=1.0, spot=100.0, strike=100.0, t=0.5, r=0.06, q=0.0)
    assert not flag.passed


def test_calendar_variance_flag_reflects_forward_vol_validity():
    valid_fv = forward_vol(0.14, 1 / 12, 0.18, 3 / 12)
    flag = check_calendar_variance(valid_fv, "1M", "3M")
    assert flag.passed

    invalid_fv = forward_vol(0.60, 0.25, 0.20, 0.30)
    flag2 = check_calendar_variance(invalid_fv, "1M", "1.2M")
    assert not flag2.passed


def test_butterfly_convexity_flags_deeply_negative_butterfly():
    flag = check_butterfly_convexity(-0.05, "25", tolerance=-0.005)
    assert not flag.passed
    flag_ok = check_butterfly_convexity(0.01, "25", tolerance=-0.005)
    assert flag_ok.passed


def test_bid_ask_consistency():
    assert check_bid_ask(10.0, 10.5).passed
    assert not check_bid_ask(10.5, 10.0).passed
