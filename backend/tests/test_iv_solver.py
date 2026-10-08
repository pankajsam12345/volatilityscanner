from app.analytics.black_scholes import BSInputs, price
from app.analytics.iv_solver import IVStatus, solve_iv


def test_round_trip_recovers_known_sigma():
    true_sigma = 0.245
    inputs = BSInputs(spot=100.0, strike=105.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.01, sigma=true_sigma, option_type="CALL")
    market_price = price(inputs)
    result = solve_iv(
        market_price=market_price, spot=100.0, strike=105.0, time_to_expiry=0.5,
        rate=0.06, dividend_yield=0.01, option_type="CALL",
    )
    assert result.status == IVStatus.VALID
    assert abs(result.iv - true_sigma) < 1e-4


def test_round_trip_for_put():
    true_sigma = 0.30
    inputs = BSInputs(spot=100.0, strike=95.0, time_to_expiry=0.25, rate=0.05, dividend_yield=0.0, sigma=true_sigma, option_type="PUT")
    market_price = price(inputs)
    result = solve_iv(
        market_price=market_price, spot=100.0, strike=95.0, time_to_expiry=0.25,
        rate=0.05, dividend_yield=0.0, option_type="PUT",
    )
    assert result.status == IVStatus.VALID
    assert abs(result.iv - true_sigma) < 1e-4


def test_expired_option_returns_insufficient_data():
    result = solve_iv(market_price=5.0, spot=100.0, strike=100.0, time_to_expiry=0.0, rate=0.06, dividend_yield=0.0, option_type="CALL")
    assert result.status == IVStatus.INSUFFICIENT_DATA
    assert result.iv is None


def test_non_positive_price_returns_invalid_price():
    result = solve_iv(market_price=0.0, spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0, option_type="CALL")
    assert result.status == IVStatus.INVALID_PRICE


def test_price_below_intrinsic_returns_arbitrage_violation():
    # Deep ITM call priced below its no-arbitrage floor (S - K*e^-rT)
    result = solve_iv(market_price=0.01, spot=150.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0, option_type="CALL")
    assert result.status == IVStatus.ARBITRAGE_VIOLATION


def test_wide_spread_flagged():
    inputs = BSInputs(spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0, sigma=0.2, option_type="CALL")
    mid = price(inputs)
    result = solve_iv(
        market_price=mid, spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0,
        option_type="CALL", bid=mid * 0.5, ask=mid * 1.5, wide_spread_pct_threshold=25.0,
    )
    assert result.status == IVStatus.WIDE_SPREAD


def test_bid_greater_than_ask_flagged_as_arbitrage_violation():
    inputs = BSInputs(spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0, sigma=0.2, option_type="CALL")
    mid = price(inputs)
    result = solve_iv(
        market_price=mid, spot=100.0, strike=100.0, time_to_expiry=0.5, rate=0.06, dividend_yield=0.0,
        option_type="CALL", bid=mid + 1, ask=mid,
    )
    assert result.status == IVStatus.ARBITRAGE_VIOLATION
