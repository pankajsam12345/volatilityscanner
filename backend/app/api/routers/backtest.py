from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.strategy import LegSpecIn
from app.backtesting.stats import equity_curve as compute_equity_curve
from app.core.config import get_settings
from app.core.database import get_db
from app.models import BacktestRun, BacktestTrade, Underlying, User
from app.services.backtest_service import BacktestError, run_and_persist_backtest, run_and_persist_chain_backtest
from app.strategies.builder import StrategyLegSpec
from app.strategies.templates import build_template_legs

router = APIRouter()


class BacktestRequest(BaseModel):
    symbol: str
    signal_type: str  # IV_RV | CALENDAR | FORWARD_VOL | SKEW | RR | BF
    bucket: str  # tenor label ("1M"), near_far ("1M_3M"), or "TENOR:DELTA" ("1M:25") for SKEW/RR/BF
    entry_zscore: Optional[float] = None
    exit_zscore: Optional[float] = None
    max_holding_days: Optional[int] = None
    rolling_window_days: Optional[int] = None
    transaction_cost_vol_points: Optional[float] = None
    # CHAIN replays a real multi-leg strategy against historical option
    # chains instead of a scalar metric delta (see app/backtesting/chain_replay.py)
    # — requires either 'legs' or 'template_key', ignores transaction_cost_vol_points
    # (real per-leg bid/ask cost is used instead).
    replay_mode: Literal["SIGNAL", "CHAIN"] = "SIGNAL"
    template_key: Optional[str] = None
    template_params: dict = {}
    legs: Optional[list[LegSpecIn]] = None


def _run_to_summary_dict(run: BacktestRun, symbol: str) -> dict:
    return {
        "id": run.id, "symbol": symbol, "signal_type": run.signal_type, "bucket": run.bucket,
        "replay_mode": run.replay_mode, "params": run.params, "summary": run.summary, "created_at": run.created_at,
    }


async def _trades_for_run(db: AsyncSession, run: BacktestRun) -> list[BacktestTrade]:
    return (await db.execute(select(BacktestTrade).where(BacktestTrade.run_id == run.id).order_by(BacktestTrade.entry_date))).scalars().all()


def _trade_to_dict(t: BacktestTrade) -> dict:
    return {
        "entry_date": t.entry_date, "exit_date": t.exit_date, "direction": t.direction,
        "entry_value": t.entry_value, "exit_value": t.exit_value, "entry_zscore": t.entry_zscore,
        "exit_zscore": t.exit_zscore, "holding_days": t.holding_days, "gross_pnl": t.gross_pnl,
        "transaction_cost": t.transaction_cost, "net_pnl": t.net_pnl, "regime_at_entry": t.regime_at_entry,
        "legs": t.legs,
    }


@router.post("/backtest")
async def post_backtest(body: BacktestRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    settings = get_settings()
    entry_z = body.entry_zscore if body.entry_zscore is not None else settings.zscore_extreme_threshold
    exit_z = body.exit_zscore if body.exit_zscore is not None else settings.zscore_extreme_threshold / 4
    max_holding = body.max_holding_days or settings.backtest_max_holding_days
    rolling_window = body.rolling_window_days or settings.backtest_rolling_window_days

    try:
        if body.replay_mode == "CHAIN":
            if body.legs:
                leg_specs = [StrategyLegSpec(l.option_type, l.target_abs_delta, l.action, l.quantity) for l in body.legs]
            elif body.template_key:
                template_params = dict(body.template_params)
                if body.template_key in ("straddle", "strangle") and "action" not in template_params:
                    # These two templates default to BUY (a sensible default
                    # for the live Strategy Builder) but a SHORT chain-replay
                    # window is meant to sell rich vol — leaving BUY here
                    # would trade backwards relative to the signal timing
                    # (see _legs_for_direction in chain_replay.py).
                    template_params["action"] = "SELL"
                try:
                    leg_specs = build_template_legs(body.template_key, **template_params)
                except (ValueError, TypeError) as exc:
                    raise HTTPException(422, str(exc))
            else:
                raise HTTPException(422, "replay_mode='CHAIN' requires either 'legs' or 'template_key'")
            run = await run_and_persist_chain_backtest(
                db, body.symbol, body.signal_type.upper(), body.bucket, leg_specs,
                entry_z, exit_z, max_holding, rolling_window, settings,
            )
        else:
            run = await run_and_persist_backtest(
                db, body.symbol, body.signal_type.upper(), body.bucket,
                entry_z, exit_z, max_holding, rolling_window,
                body.transaction_cost_vol_points if body.transaction_cost_vol_points is not None else settings.backtest_transaction_cost_vol_points,
                settings,
            )
    except BacktestError as exc:
        raise HTTPException(404, str(exc))

    trades = await _trades_for_run(db, run)
    result = _run_to_summary_dict(run, body.symbol)
    result["trades"] = [_trade_to_dict(t) for t in trades]
    result["regime_breakdown"] = run.regime_breakdown
    result["equity_curve"] = compute_equity_curve([_TradeShim(t) for t in trades])
    return result


class _TradeShim:
    """Adapts an ORM BacktestTrade row to the plain-dataclass interface equity_curve() expects."""
    def __init__(self, t: BacktestTrade):
        self.exit_date = t.exit_date
        self.net_pnl = t.net_pnl


@router.get("/backtest")
async def list_backtests(symbol: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(BacktestRun, Underlying.symbol).join(Underlying).order_by(BacktestRun.created_at.desc())
    if symbol:
        stmt = stmt.where(Underlying.symbol == symbol)
    rows = (await db.execute(stmt)).all()
    return [_run_to_summary_dict(run, sym) for run, sym in rows]


@router.get("/backtest/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(BacktestRun, Underlying.symbol).join(Underlying).where(BacktestRun.id == run_id))).first()
    if row is None:
        raise HTTPException(404, f"No backtest run {run_id}")
    run, symbol = row
    trades = await _trades_for_run(db, run)
    result = _run_to_summary_dict(run, symbol)
    result["trades"] = [_trade_to_dict(t) for t in trades]
    result["regime_breakdown"] = run.regime_breakdown
    result["equity_curve"] = compute_equity_curve([_TradeShim(t) for t in trades])
    return result
