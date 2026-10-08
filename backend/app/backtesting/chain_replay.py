"""
Full option-chain replay backtest: reuses find_trade_windows (the same
walk-forward entry/exit signal timing as the scalar signal backtest,
app/backtesting/engine.py) but marks P&L using REAL historical option
prices instead of a scalar metric delta — resolving a user-specified
multi-leg strategy's strikes at entry via delta lookup, then marking those
same held contracts to market at exit.

Requires scripts/seed.py's historical option-chain backfill (a single
rolling near-month expiry per historical day — see README known
limitations); trade windows whose entry/exit day falls outside that
coverage are silently skipped (not every day in the signal series
necessarily has a matching historical chain, e.g. the warm-up period).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.engine import Trade, TradeWindow
from app.costs.transaction_cost import leg_transaction_cost
from app.models import Expiry, Option
from app.services.volatility_service import build_expiry_snapshot_as_of
from app.strategies.builder import StrategyLegSpec, StrategyResolutionError, resolve_legs

_FLIP_ACTION = {"BUY": "SELL", "SELL": "BUY"}


@dataclass(frozen=True)
class ChainTrade(Trade):
    legs: list  # [{"option_type", "action", "quantity", "strike", "entry_price", "exit_price"}, ...]


def _legs_for_direction(leg_specs: list[StrategyLegSpec], direction: str) -> list[StrategyLegSpec]:
    """
    leg_specs are configured for the SHORT-signal case (e.g. "sell a
    straddle when vol looks rich"). When a window's direction is LONG (the
    metric looks cheap instead), every leg's action is inverted (SELL<->BUY)
    to express the opposite trade with the same strikes/quantities —
    mirroring how the scalar engine treats SHORT/LONG as sign-flips of the
    same underlying position.
    """
    if direction == "SHORT":
        return leg_specs
    return [StrategyLegSpec(s.option_type, s.target_abs_delta, _FLIP_ACTION[s.action], s.quantity) for s in leg_specs]


async def _expiry_id_for_day(session: AsyncSession, underlying_id: int, as_of_date: dt.date) -> int | None:
    """
    Whichever expiry(s) actually have a persisted chain on this historical
    day — normally exactly one (the seed's single rolling near-month
    expiry). If more than one exists (e.g. as_of_date happens to be "today",
    which gets the full multi-expiry live ladder instead), picks whichever
    is nearest to a 30-day tenor, consistent with the historical ladder's
    own selection rule.
    """
    ts = dt.datetime.combine(as_of_date, dt.time(15, 30))
    rows = (
        await session.execute(
            select(Expiry.id, Expiry.expiry_date)
            .join(Option, Option.expiry_id == Expiry.id)
            .where(Option.underlying_id == underlying_id, Option.timestamp == ts)
            .distinct()
        )
    ).all()
    if not rows:
        return None
    target = as_of_date + dt.timedelta(days=30)
    return min(rows, key=lambda r: abs((r.expiry_date - target).days)).id


async def replay_strategy_trades(
    session: AsyncSession,
    underlying_id: int,
    lot_size: int,
    leg_specs: list[StrategyLegSpec],
    trade_windows: list[TradeWindow],
    regime_by_date: dict[dt.date, str],
    settings,
) -> list[ChainTrade]:
    trades: list[ChainTrade] = []

    for w in trade_windows:
        specs = _legs_for_direction(leg_specs, w.direction)

        entry_expiry_id = await _expiry_id_for_day(session, underlying_id, w.entry_date)
        if entry_expiry_id is None:
            continue
        entry_snapshot = await build_expiry_snapshot_as_of(session, entry_expiry_id, w.entry_date)
        if entry_snapshot is None:
            continue
        try:
            resolved_entry, _, _, entry_net_premium, entry_cost = resolve_legs(
                entry_snapshot, specs, lot_size, settings, context=f"entry {w.entry_date}",
            )
        except StrategyResolutionError:
            continue

        # Mark the SAME held contracts to market at exit — never re-resolve
        # by delta, which would silently swap to a different strike.
        exit_snapshot = await build_expiry_snapshot_as_of(session, entry_expiry_id, w.exit_date)
        if exit_snapshot is None:
            continue

        leg_details = []
        gross_pnl = 0.0
        exit_cost = 0.0
        missing = False
        for leg, spec in zip(resolved_entry, specs):
            exit_opt = exit_snapshot.option_by_key.get((leg.strike, leg.option_type))
            if exit_opt is None:
                missing = True
                break
            entry_mid = (leg.bid + leg.ask) / 2
            exit_mid = (exit_opt.bid + exit_opt.ask) / 2
            sign = 1 if spec.action == "BUY" else -1
            gross_pnl += sign * (exit_mid - entry_mid) * spec.quantity * lot_size
            exit_cost += leg_transaction_cost(exit_opt.bid, exit_opt.ask, None, lot_size, settings).cash_cost * spec.quantity
            leg_details.append({
                "option_type": leg.option_type, "action": spec.action, "quantity": spec.quantity,
                "strike": leg.strike, "entry_price": round(entry_mid, 2), "exit_price": round(exit_mid, 2),
            })
        if missing:
            continue

        transaction_cost = entry_cost + exit_cost
        net_pnl = gross_pnl - transaction_cost
        trades.append(ChainTrade(
            entry_date=w.entry_date, exit_date=w.exit_date, direction=w.direction,
            entry_value=round(entry_net_premium * lot_size, 2), exit_value=round(entry_net_premium * lot_size + gross_pnl, 2),
            entry_zscore=w.entry_zscore, exit_zscore=w.exit_zscore,
            holding_days=(w.exit_date - w.entry_date).days,
            gross_pnl=gross_pnl, transaction_cost=transaction_cost, net_pnl=net_pnl,
            regime_at_entry=regime_by_date.get(w.entry_date, "UNKNOWN"),
            legs=leg_details,
        ))

    return trades
