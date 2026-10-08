from types import SimpleNamespace

from app.costs.transaction_cost import leg_transaction_cost, strategy_transaction_cost

SETTINGS = SimpleNamespace(
    slippage_vol_points=0.15, market_impact_vol_points=0.10, hedging_cost_vol_points=0.05,
    brokerage_per_lot=20.0, exchange_fee_pct=0.0005, tax_pct=0.0006,
)


def test_leg_cost_includes_bid_ask_slippage_and_impact():
    # vega=20 per 100 vol points -> price-per-vol-point = 0.20; half-spread=0.50 -> bid_ask_cost_vol=2.5
    cost = leg_transaction_cost(bid=9.50, ask=10.50, vega=20.0, lot_size=50, settings=SETTINGS)
    assert abs(cost.bid_ask_cost_vol - 2.5) < 1e-9
    assert cost.slippage_vol == SETTINGS.slippage_vol_points
    assert cost.market_impact_vol == SETTINGS.market_impact_vol_points
    assert abs(cost.total_vol_cost - (2.5 + 0.15 + 0.10)) < 1e-9
    assert cost.cash_cost > 0


def test_leg_cost_zero_vega_skips_bid_ask_vol_conversion():
    cost = leg_transaction_cost(bid=9.50, ask=10.50, vega=0.0, lot_size=50, settings=SETTINGS)
    assert cost.bid_ask_cost_vol == 0.0
    assert cost.total_vol_cost == SETTINGS.slippage_vol_points + SETTINGS.market_impact_vol_points


def test_strategy_cost_sums_legs_and_adds_hedging_cost():
    leg1 = leg_transaction_cost(9.5, 10.5, 20.0, 50, SETTINGS)
    leg2 = leg_transaction_cost(4.5, 5.0, 15.0, 50, SETTINGS)
    strat = strategy_transaction_cost(gross_edge=3.0, legs=[leg1, leg2], settings=SETTINGS)
    assert abs(strat.total_vol_cost - (leg1.total_vol_cost + leg2.total_vol_cost)) < 1e-9
    assert abs(strat.breakeven_cost - (strat.total_vol_cost + SETTINGS.hedging_cost_vol_points)) < 1e-9
    assert strat.total_cash_cost == leg1.cash_cost + leg2.cash_cost
