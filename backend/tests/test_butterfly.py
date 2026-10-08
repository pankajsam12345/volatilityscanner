from app.analytics.butterfly import butterfly_metrics


def test_butterfly_matches_formula():
    # BF25 = 0.5*(put25 + call25) - atm
    grid = {"put_25d_iv": 0.22, "call_25d_iv": 0.19}
    atm = 0.18
    out = butterfly_metrics(grid, atm, deltas=[25])
    expected = 0.5 * (0.22 + 0.19) - 0.18
    assert abs(out["bf_25"] - expected) < 1e-9


def test_butterfly_non_negative_for_convex_smile():
    # A convex smile (wings >= atm) should produce non-negative butterfly
    grid = {"put_25d_iv": 0.20, "call_25d_iv": 0.20}
    atm = 0.18
    out = butterfly_metrics(grid, atm, deltas=[25])
    assert out["bf_25"] >= 0


def test_butterfly_missing_inputs_returns_none():
    grid = {"put_25d_iv": None, "call_25d_iv": 0.19}
    out = butterfly_metrics(grid, 0.18, deltas=[25])
    assert out["bf_25"] is None
