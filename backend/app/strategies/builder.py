"""
Strategy Builder (§34): resolves a list of abstract leg specs (option type +
target delta + action + quantity) against today's real option chain, then
computes net premium, aggregated Greeks, transaction cost, a full expiry
payoff diagram, breakevens, and max risk/reward (flagging undefined bounds
explicitly rather than fabricating a number).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.costs.transaction_cost import leg_transaction_cost
from app.models import Expiry, Underlying
from app.opportunities.greeks_aggregator import aggregate_strategy_greeks
from app.services.volatility_service import ExpirySnapshot, build_expiry_snapshot
from app.strategies.payoff import PayoffLeg, default_spot_grid, find_breakevens, payoff_curve, risk_reward_bounds

GREEK_KEYS = ["delta", "gamma", "vega", "theta", "rho", "vanna", "volga", "charm"]


@dataclass(frozen=True)
class StrategyLegSpec:
    option_type: str  # CALL | PUT
    target_abs_delta: float  # 0..1; 0.5 ~= ATM
    action: str  # BUY | SELL
    quantity: int = 1


@dataclass(frozen=True)
class ResolvedLeg:
    option_type: str
    action: str
    quantity: int
    strike: float
    iv: float | None
    bid: float
    ask: float
    greeks: dict

    def as_dict(self) -> dict:
        return {
            "option_type": self.option_type, "action": self.action, "quantity": self.quantity,
            "strike": self.strike, "iv": self.iv, "bid": self.bid, "ask": self.ask, "greeks": self.greeks,
        }


@dataclass(frozen=True)
class StrategyAnalysis:
    symbol: str
    expiry_date: dt.date
    legs: list[ResolvedLeg]
    net_premium: float
    greeks: dict
    transaction_cost_cash: float
    payoff_curve: list[tuple[float, float]]
    breakevens: list[float]
    max_risk: float | None
    max_reward: float | None
    undefined_risk: bool
    undefined_reward: bool


class StrategyResolutionError(Exception):
    pass


def resolve_legs(
    es: ExpirySnapshot, leg_specs: list[StrategyLegSpec], lot_size: int, settings, context: str = "",
) -> tuple[list[ResolvedLeg], list[PayoffLeg], list[dict], float, float]:
    """
    Delta->strike leg resolution against any ExpirySnapshot — live (via
    build_expiry_snapshot) or historical (via build_expiry_snapshot_as_of,
    used by the chain-replay backtester) — so this logic isn't duplicated
    between the live Strategy Builder and the backtester.
    Returns (resolved_legs, payoff_legs, leg_greeks_list, net_premium, transaction_cost_cash).
    """
    resolved: list[ResolvedLeg] = []
    payoff_legs: list[PayoffLeg] = []
    leg_greeks_list: list[dict] = []
    net_premium = 0.0
    transaction_cost_cash = 0.0

    for spec in leg_specs:
        match = es.find_nearest_by_delta(spec.option_type, spec.target_abs_delta)
        if match is None:
            raise StrategyResolutionError(f"No {spec.option_type} option near {spec.target_abs_delta:.0%} delta {context}".strip())
        (strike, _), snap = match
        opt = es.option_by_key[(strike, spec.option_type)]
        mid = (opt.bid + opt.ask) / 2

        greeks = {k: getattr(snap, k) for k in GREEK_KEYS}
        resolved.append(ResolvedLeg(spec.option_type, spec.action, spec.quantity, strike, snap.iv, opt.bid, opt.ask, greeks))
        payoff_legs.append(PayoffLeg(strike, spec.option_type, spec.action, mid, spec.quantity))
        leg_greeks_list.append(greeks)

        sign = 1 if spec.action == "BUY" else -1
        net_premium += sign * mid * spec.quantity

        leg_cost = leg_transaction_cost(opt.bid, opt.ask, snap.vega, lot_size, settings)
        transaction_cost_cash += leg_cost.cash_cost * spec.quantity

    return resolved, payoff_legs, leg_greeks_list, net_premium, transaction_cost_cash


async def analyze_strategy(
    session: AsyncSession, symbol: str, expiry_date: dt.date, leg_specs: list[StrategyLegSpec], settings,
) -> StrategyAnalysis:
    underlying = (await session.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if underlying is None:
        raise StrategyResolutionError(f"Unknown symbol '{symbol}'")

    expiry = (
        await session.execute(select(Expiry).where(Expiry.underlying_id == underlying.id, Expiry.expiry_date == expiry_date))
    ).scalar_one_or_none()
    if expiry is None:
        raise StrategyResolutionError(f"No expiry {expiry_date} for '{symbol}'")

    es: ExpirySnapshot | None = await build_expiry_snapshot(session, underlying, expiry, settings)
    if es is None:
        raise StrategyResolutionError(f"No live option-chain snapshot for '{symbol}' {expiry_date}")

    resolved, payoff_legs, leg_greeks_list, net_premium, transaction_cost_cash = resolve_legs(
        es, leg_specs, underlying.lot_size, settings, context=f"for '{symbol}' {expiry_date}",
    )

    aggregated_greeks = aggregate_strategy_greeks(
        [spec.action for spec in leg_specs], leg_greeks_list, [spec.quantity for spec in leg_specs],
    )

    grid = default_spot_grid(underlying.spot_price)
    curve = payoff_curve(payoff_legs, grid)
    bounds = risk_reward_bounds(payoff_legs, curve)
    breakevens = find_breakevens(curve)

    return StrategyAnalysis(
        symbol=symbol, expiry_date=expiry_date, legs=resolved, net_premium=net_premium,
        greeks=aggregated_greeks, transaction_cost_cash=transaction_cost_cash,
        payoff_curve=curve, breakevens=breakevens,
        max_risk=bounds["max_risk"], max_reward=bounds["max_reward"],
        undefined_risk=bounds["undefined_risk"], undefined_reward=bounds["undefined_reward"],
    )
