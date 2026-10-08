from app.analytics.risk_reversal import risk_reversal_metrics


def test_risk_reversal_matches_spec_example():
    # §55 example: 25Δ Put IV = 22%, 25Δ Call IV = 17% -> RR = -5 vol
    grid = {"put_25d_iv": 0.22, "call_25d_iv": 0.17}
    out = risk_reversal_metrics(grid, deltas=[25])
    assert abs(out["rr_25"] - (-0.05)) < 1e-9


def test_risk_reversal_missing_leg_returns_none():
    grid = {"put_25d_iv": 0.22, "call_25d_iv": None}
    out = risk_reversal_metrics(grid, deltas=[25])
    assert out["rr_25"] is None


def test_risk_reversal_multiple_deltas():
    grid = {
        "put_10d_iv": 0.28, "call_10d_iv": 0.15,
        "put_25d_iv": 0.22, "call_25d_iv": 0.17,
    }
    out = risk_reversal_metrics(grid, deltas=[10, 25])
    assert abs(out["rr_10"] - (0.15 - 0.28)) < 1e-9
    assert abs(out["rr_25"] - (0.17 - 0.22)) < 1e-9
