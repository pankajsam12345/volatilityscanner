from app.simulation.monte_carlo import simulate_monte_carlo


def test_zero_greeks_gives_zero_mean_and_zero_var():
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_monte_carlo(greeks, net_premium=0.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.0, daily_spot_vol=0.01, horizon_days=10, num_paths=500)
    assert abs(result["mean_pnl"]) < 1e-9
    assert result["var_95"] == 0.0
    assert result["cvar_95"] == 0.0


def test_probabilities_sum_to_100():
    greeks = {"delta": 1.0, "gamma": 0.1, "theta": -1.0, "vega": 5.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_monte_carlo(greeks, net_premium=50.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.05, daily_spot_vol=0.01, horizon_days=20, num_paths=1000)
    assert abs(result["prob_profit"] + result["prob_loss"] - 100.0) < 1e-6


def test_cvar_is_at_least_as_severe_as_var():
    greeks = {"delta": 0.0, "gamma": 1.0, "theta": -2.0, "vega": 20.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_monte_carlo(greeks, net_premium=100.0, spot0=100.0, sigma0_vol_points=20.0, rate=0.05, daily_spot_vol=0.015, horizon_days=15, num_paths=2000)
    assert result["cvar_95"] >= result["var_95"] - 1e-6  # expected shortfall in the tail is at least as bad as the VaR cutoff


def test_distribution_sample_length_matches_num_paths():
    greeks = {"delta": 1.0, "gamma": 0.1, "theta": -1.0, "vega": 5.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_monte_carlo(greeks, 0.0, 100.0, 20.0, 0.0, 0.01, 10, 777)
    assert len(result["pnl_distribution_sample"]) == 777


def test_deterministic_given_same_seed():
    greeks = {"delta": 1.0, "gamma": 0.1, "theta": -1.0, "vega": 5.0, "vanna": 0.0, "volga": 0.0}
    r1 = simulate_monte_carlo(greeks, 0.0, 100.0, 20.0, 0.0, 0.01, 10, 500, seed=1)
    r2 = simulate_monte_carlo(greeks, 0.0, 100.0, 20.0, 0.0, 0.01, 10, 500, seed=1)
    assert r1["mean_pnl"] == r2["mean_pnl"]


def test_long_gamma_position_has_positive_expected_pnl_from_volatility():
    # A long-gamma, no-delta, no-theta, no-vega position should show a
    # positive mean P&L purely from convexity (Jensen's inequality: E[0.5*gamma*dS^2] >= 0).
    greeks = {"delta": 0.0, "gamma": 3.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "volga": 0.0}
    result = simulate_monte_carlo(greeks, 0.0, 100.0, 20.0, 0.0, 0.02, 20, 3000)
    assert result["mean_pnl"] > 0
