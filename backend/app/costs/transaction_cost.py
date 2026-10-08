"""
Transaction cost engine (§22). Costs are expressed in *vol points* wherever
possible so they net directly against edges that are themselves measured in
vol points (IV-RV spread, calendar spread, RR, BF). Bid-ask cost is
converted price -> vol points by dividing by the leg's vega. A parallel
cash-based estimate (brokerage/fees/tax/bid-ask in currency) is also
reported for realism/display, per §22's required cost breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegCost:
    bid_ask_cost_vol: float
    slippage_vol: float
    market_impact_vol: float
    total_vol_cost: float
    cash_cost: float


@dataclass(frozen=True)
class StrategyCost:
    gross_edge: float
    total_vol_cost: float
    hedging_cost_vol: float
    net_edge: float
    total_cash_cost: float
    breakeven_cost: float  # = total_vol_cost + hedging_cost_vol; the edge needed just to break even
    legs: list[LegCost]


def leg_transaction_cost(
    bid: float, ask: float, vega: float | None, lot_size: int, settings,
) -> LegCost:
    mid = (bid + ask) / 2
    half_spread_cash = max(ask - bid, 0.0) / 2

    if vega is not None and abs(vega) > 1e-6:
        # vega is "per 1.00 (100 vol points) of sigma" (see black_scholes.py) ->
        # divide by 100 to get price-per-1-vol-point, then invert.
        price_per_vol_point = vega / 100
        bid_ask_cost_vol = half_spread_cash / price_per_vol_point if price_per_vol_point > 1e-9 else 0.0
    else:
        bid_ask_cost_vol = 0.0

    total_vol_cost = bid_ask_cost_vol + settings.slippage_vol_points + settings.market_impact_vol_points
    cash_cost = (
        settings.brokerage_per_lot
        + mid * lot_size * settings.exchange_fee_pct
        + mid * lot_size * settings.tax_pct
        + half_spread_cash * lot_size
    )
    return LegCost(
        bid_ask_cost_vol=bid_ask_cost_vol,
        slippage_vol=settings.slippage_vol_points,
        market_impact_vol=settings.market_impact_vol_points,
        total_vol_cost=total_vol_cost,
        cash_cost=cash_cost,
    )


def strategy_transaction_cost(gross_edge: float, legs: list[LegCost], settings) -> StrategyCost:
    total_vol_cost = sum(leg.total_vol_cost for leg in legs)
    hedging_cost_vol = settings.hedging_cost_vol_points
    total_cash_cost = sum(leg.cash_cost for leg in legs)
    breakeven_cost = total_vol_cost + hedging_cost_vol
    net_edge = gross_edge - breakeven_cost
    return StrategyCost(
        gross_edge=gross_edge,
        total_vol_cost=total_vol_cost,
        hedging_cost_vol=hedging_cost_vol,
        net_edge=net_edge,
        total_cash_cost=total_cash_cost,
        breakeven_cost=breakeven_cost,
        legs=legs,
    )
