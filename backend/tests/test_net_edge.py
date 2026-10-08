from types import SimpleNamespace

from app.costs.transaction_cost import leg_transaction_cost, strategy_transaction_cost

SETTINGS = SimpleNamespace(
    slippage_vol_points=0.15, market_impact_vol_points=0.10, hedging_cost_vol_points=0.05,
    brokerage_per_lot=20.0, exchange_fee_pct=0.0005, tax_pct=0.0006,
)


def test_net_edge_matches_spec_worked_example():
    # §25 worked example: gross edge +2.3 vol, transaction cost -0.35 vol -> net edge +1.95 vol
    gross_edge = 2.3
    # Construct legs whose combined vol cost + hedging cost totals ~0.35
    leg = leg_transaction_cost(bid=0.0, ask=0.0, vega=None, lot_size=50, settings=SETTINGS)
    # override to hit the exact spec figure for a clean assertion
    strat = strategy_transaction_cost(gross_edge, [leg], SimpleNamespace(**{**SETTINGS.__dict__, "slippage_vol_points": 0.15, "market_impact_vol_points": 0.10, "hedging_cost_vol_points": 0.10}))
    assert abs(strat.breakeven_cost - 0.35) < 1e-9
    assert abs(strat.net_edge - 1.95) < 1e-9


def test_net_edge_goes_negative_when_costs_exceed_gross_edge():
    leg = leg_transaction_cost(bid=9.0, ask=11.0, vega=5.0, lot_size=50, settings=SETTINGS)
    strat = strategy_transaction_cost(gross_edge=0.5, legs=[leg], settings=SETTINGS)
    assert strat.net_edge < 0
    assert strat.breakeven_cost > strat.gross_edge


def test_net_edge_positive_when_gross_edge_comfortably_exceeds_costs():
    leg = leg_transaction_cost(bid=9.9, ask=10.1, vega=50.0, lot_size=50, settings=SETTINGS)
    strat = strategy_transaction_cost(gross_edge=5.0, legs=[leg], settings=SETTINGS)
    assert strat.net_edge > 0
    assert abs(strat.net_edge - (strat.gross_edge - strat.breakeven_cost)) < 1e-9
