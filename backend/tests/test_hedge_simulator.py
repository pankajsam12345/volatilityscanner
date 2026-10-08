from app.simulation.hedge_simulator import FREQUENCY_STEPS_PER_DAY, simulate_hedge


def test_zero_greeks_and_premium_yields_zero_pnl_and_zero_cost():
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_hedge(greeks, net_premium=0.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.0, daily_spot_vol=0.01, num_days=10, rehedge_frequency="daily")
    assert result["totals"]["gross_pnl"] == 0.0
    assert result["totals"]["transaction_cost"] == 0.0
    assert result["totals"]["net_pnl"] == 0.0


def test_daily_records_length_matches_num_days():
    greeks = {"delta": 1.0, "gamma": 0.5, "theta": -1.0, "vega": 10.0, "vanna": 0.1, "volga": 0.2}
    result = simulate_hedge(greeks, net_premium=100.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.05, daily_spot_vol=0.01, num_days=15, rehedge_frequency="hourly")
    assert len(result["cumulative"]) == 15
    assert result["cumulative"][0]["day"] == 1
    assert result["cumulative"][-1]["day"] == 15


def test_positive_gamma_produces_nonnegative_aggregate_gamma_pnl():
    greeks = {"delta": 0.0, "gamma": 2.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_hedge(greeks, net_premium=0.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.0, daily_spot_vol=0.02, num_days=30, rehedge_frequency="daily")
    assert result["totals"]["gamma_pnl"] >= 0


def test_theta_only_position_loses_over_time():
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": -5.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_hedge(greeks, net_premium=0.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.0, daily_spot_vol=0.0001, num_days=10, rehedge_frequency="daily")
    assert result["totals"]["theta_pnl"] < 0
    assert abs(result["totals"]["theta_pnl"] - (-50.0)) < 1e-6  # -5/day * 10 days


def test_deterministic_given_same_seed():
    greeks = {"delta": 1.0, "gamma": 0.5, "theta": -1.0, "vega": 10.0, "vanna": 0.1, "volga": 0.2}
    r1 = simulate_hedge(greeks, 100.0, 100.0, 20.0, 0.05, 0.01, 20, "daily", seed=42)
    r2 = simulate_hedge(greeks, 100.0, 100.0, 20.0, 0.05, 0.01, 20, "daily", seed=42)
    assert r1["totals"]["net_pnl"] == r2["totals"]["net_pnl"]


def test_unknown_frequency_raises():
    import pytest
    with pytest.raises(ValueError):
        simulate_hedge({}, 0.0, 100.0, 20.0, 0.0, 0.01, 5, "weekly")


def test_all_frequencies_are_runnable():
    greeks = {"delta": 1.0, "gamma": 0.5, "theta": -1.0, "vega": 10.0, "vanna": 0.1, "volga": 0.2}
    for freq in FREQUENCY_STEPS_PER_DAY:
        result = simulate_hedge(greeks, 100.0, 100.0, 20.0, 0.05, 0.01, 5, freq)
        assert result["rehedge_frequency"] == freq
        assert len(result["cumulative"]) == 5
