from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Opportunity, Underlying, User
from app.services.opportunity_service import generate_opportunities

router = APIRouter()

SORT_FIELDS = {
    "net_edge": Opportunity.net_edge, "score": Opportunity.score, "confidence": Opportunity.confidence,
    "risk_reward": Opportunity.risk_reward, "max_risk": Opportunity.max_risk, "gross_edge": Opportunity.gross_edge,
}


def _to_dict(row: Opportunity, symbol: str) -> dict:
    return {
        "id": row.id, "symbol": symbol, "timestamp": row.timestamp, "expiry_id": row.expiry_id,
        "strategy": row.strategy, "signal_type": row.signal_type, "direction": row.direction,
        "score": row.score, "score_components": row.score_components, "confidence": row.confidence,
        "gross_edge": row.gross_edge, "transaction_cost": row.transaction_cost, "net_edge": row.net_edge,
        "max_risk": row.max_risk, "expected_return": row.expected_return, "risk_reward": row.risk_reward,
        "liquidity_status": row.liquidity_status, "data_quality": row.data_quality,
        "legs": row.legs, "greeks": row.greeks, "historical_context": row.historical_context,
        "no_arbitrage_flags": row.no_arbitrage_flags, "explanation": row.explanation, "is_demo": row.is_demo,
    }


async def _latest_timestamp_subquery(db, underlying_id: int):
    return (
        await db.execute(select(func.max(Opportunity.timestamp)).where(Opportunity.underlying_id == underlying_id))
    ).scalar_one_or_none()


@router.post("/opportunities/{symbol}/refresh")
async def refresh_opportunities(symbol: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    settings = get_settings()
    ran = await generate_opportunities(db, symbol, settings)
    if not ran:
        raise HTTPException(404, f"Unknown symbol '{symbol}' or no market data snapshot to score")
    return {"status": "ok", "symbol": symbol}


@router.get("/opportunities/{symbol}")
async def list_opportunities_for_symbol(
    symbol: str,
    min_net_edge: Optional[float] = None,
    min_confidence: Optional[float] = None,
    max_risk: Optional[float] = None,
    liquidity: Optional[str] = None,
    strategy: Optional[str] = None,
    sort_by: str = Query("net_edge", pattern="^(net_edge|score|confidence|risk_reward|max_risk|gross_edge)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    latest_ts = await _latest_timestamp_subquery(db, u.id)
    if latest_ts is None:
        return []

    stmt = select(Opportunity).where(Opportunity.underlying_id == u.id, Opportunity.timestamp == latest_ts)
    if min_net_edge is not None:
        stmt = stmt.where(Opportunity.net_edge >= min_net_edge)
    if min_confidence is not None:
        stmt = stmt.where(Opportunity.confidence >= min_confidence)
    if max_risk is not None:
        stmt = stmt.where(Opportunity.max_risk <= max_risk)
    if liquidity is not None:
        stmt = stmt.where(Opportunity.liquidity_status == liquidity.upper())
    if strategy is not None:
        stmt = stmt.where(Opportunity.strategy == strategy.upper())

    field = SORT_FIELDS[sort_by]
    stmt = stmt.order_by(field.desc() if sort_dir == "desc" else field.asc())

    rows = (await db.execute(stmt)).scalars().all()
    return [_to_dict(r, symbol) for r in rows]


@router.get("/opportunities")
async def list_all_opportunities(
    min_net_edge: Optional[float] = None,
    min_confidence: Optional[float] = None,
    max_risk: Optional[float] = None,
    liquidity: Optional[str] = None,
    strategy: Optional[str] = None,
    sort_by: str = Query("net_edge", pattern="^(net_edge|score|confidence|risk_reward|max_risk|gross_edge)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    underlyings = (await db.execute(select(Underlying))).scalars().all()
    all_rows = []
    for u in underlyings:
        latest_ts = await _latest_timestamp_subquery(db, u.id)
        if latest_ts is None:
            continue
        stmt = select(Opportunity).where(Opportunity.underlying_id == u.id, Opportunity.timestamp == latest_ts)
        if min_net_edge is not None:
            stmt = stmt.where(Opportunity.net_edge >= min_net_edge)
        if min_confidence is not None:
            stmt = stmt.where(Opportunity.confidence >= min_confidence)
        if max_risk is not None:
            stmt = stmt.where(Opportunity.max_risk <= max_risk)
        if liquidity is not None:
            stmt = stmt.where(Opportunity.liquidity_status == liquidity.upper())
        if strategy is not None:
            stmt = stmt.where(Opportunity.strategy == strategy.upper())
        rows = (await db.execute(stmt)).scalars().all()
        all_rows.extend(_to_dict(r, u.symbol) for r in rows)

    reverse = sort_dir == "desc"
    all_rows.sort(key=lambda r: r[sort_by], reverse=reverse)
    return all_rows
