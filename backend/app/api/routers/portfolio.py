import datetime as dt
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Expiry, Position, Underlying, User
from app.risk.portfolio_risk import ES_95_MULTIPLIER, Z_95, aggregate_position_greeks, parametric_var, what_if_grid
from app.services import history_service
from app.strategies.builder import StrategyLegSpec, StrategyResolutionError, analyze_strategy
from app.strategies.templates import build_template_legs

router = APIRouter()


class LegSpecIn(BaseModel):
    option_type: str
    target_abs_delta: float
    action: str
    quantity: int = 1


class CreatePositionRequest(BaseModel):
    symbol: str
    expiry_date: dt.date
    label: str
    template_key: Optional[str] = None
    template_params: dict = {}
    legs: Optional[list[LegSpecIn]] = None
    quantity: int = 1


def _position_to_dict(p: Position, symbol: str) -> dict:
    return {
        "id": p.id, "underlying_id": p.underlying_id, "symbol": symbol, "label": p.label,
        "legs": p.legs, "quantity": p.quantity, "opened_at": p.opened_at, "is_open": p.is_open,
    }


@router.post("/portfolio/positions")
async def create_position(body: CreatePositionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    settings = get_settings()

    if body.legs:
        leg_specs = [StrategyLegSpec(l.option_type, l.target_abs_delta, l.action, l.quantity) for l in body.legs]
    elif body.template_key:
        try:
            leg_specs = build_template_legs(body.template_key, **body.template_params)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
    else:
        raise HTTPException(422, "Provide either 'legs' or 'template_key'")

    try:
        analysis = await analyze_strategy(db, body.symbol, body.expiry_date, leg_specs, settings)
    except StrategyResolutionError as exc:
        raise HTTPException(404, str(exc))

    underlying = (await db.execute(select(Underlying).where(Underlying.symbol == body.symbol))).scalar_one()
    expiry = (
        await db.execute(select(Expiry).where(Expiry.underlying_id == underlying.id, Expiry.expiry_date == body.expiry_date))
    ).scalar_one_or_none()

    position = Position(
        underlying_id=underlying.id, expiry_id=expiry.id if expiry else None, label=body.label,
        legs=[leg.as_dict() for leg in analysis.legs], quantity=body.quantity,
        opened_at=dt.datetime.now(dt.timezone.utc), is_open=True,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return _position_to_dict(position, body.symbol)


@router.get("/portfolio/positions")
async def list_positions(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Position, Underlying.symbol).join(Underlying).where(Position.is_open.is_(True)).order_by(Position.opened_at.desc()))
    ).all()
    return [_position_to_dict(p, symbol) for p, symbol in rows]


@router.delete("/portfolio/positions/{position_id}")
async def close_position(position_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    position = (await db.execute(select(Position).where(Position.id == position_id))).scalar_one_or_none()
    if position is None:
        raise HTTPException(404, f"No position {position_id}")
    position.is_open = False
    await db.commit()
    return {"status": "closed"}


def _leg_greeks(position: Position) -> list[dict]:
    return [leg["greeks"] for leg in position.legs] if position.legs else []


async def _open_positions_context(db: AsyncSession):
    rows = (
        await db.execute(select(Position, Underlying).join(Underlying).where(Position.is_open.is_(True)))
    ).all()
    return rows


@router.get("/portfolio/risk")
async def get_portfolio_risk(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    rows = await _open_positions_context(db)

    positions_out = [_position_to_dict(p, u.symbol) for p, u in rows]
    aggregated = aggregate_position_greeks([_leg_greeks(p) for p, _ in rows], [p.quantity for p, _ in rows])

    if not rows:
        return {"positions": [], "aggregated_greeks": aggregated, "var_95": 0.0, "cvar_95": 0.0}

    # Parametric VaR combines each underlying's delta/vega exposure independently
    # (a simplification — see app.risk.portfolio_risk docstring) then sums variances.
    by_underlying: dict[int, list] = {}
    for p, u in rows:
        by_underlying.setdefault(u.id, []).append((p, u))

    total_variance = 0.0
    for underlying_id, entries in by_underlying.items():
        u = entries[0][1]
        greeks = aggregate_position_greeks([_leg_greeks(p) for p, _ in entries], [p.quantity for p, _ in entries])
        rv20 = await history_service.get_latest_hv(db, underlying_id, 20)
        daily_spot_vol = (rv20 or 0.15) / (settings.trading_days_per_year ** 0.5)
        risk = parametric_var(greeks["delta"], greeks["vega"], u.spot_price, daily_spot_vol, settings.hedge_sim_vol_of_vol_points)
        total_variance += risk.daily_std ** 2

    combined_std = math.sqrt(total_variance)
    return {
        "positions": positions_out, "aggregated_greeks": aggregated,
        "var_95": combined_std * Z_95, "cvar_95": combined_std * ES_95_MULTIPLIER,
    }


class WhatIfRequest(BaseModel):
    spot_shocks_pct: Optional[list[float]] = None
    vol_shocks_pts: Optional[list[float]] = None
    time_shocks_days: Optional[list[int]] = None


@router.post("/portfolio/what-if")
async def post_what_if(body: WhatIfRequest, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    rows = await _open_positions_context(db)
    if not rows:
        raise HTTPException(404, "No open positions to shock")

    greeks = aggregate_position_greeks([_leg_greeks(p) for p, _ in rows], [p.quantity for p, _ in rows])
    reference_spot = rows[0][1].spot_price  # dominant/first underlying's spot as the shock reference

    cells = what_if_grid(
        greeks, net_premium=0.0, rate=settings.risk_free_rate, reference_spot=reference_spot,
        spot_shocks_pct=body.spot_shocks_pct or settings.whatif_spot_shocks_pct,
        vol_shocks_pts=body.vol_shocks_pts or settings.whatif_vol_shocks_pts,
        time_shocks_days=body.time_shocks_days or settings.whatif_time_shocks_days,
    )
    return {"cells": cells, "base_greeks": greeks}
