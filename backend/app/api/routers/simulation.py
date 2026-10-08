import datetime as dt
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service
from app.simulation.hedge_simulator import FREQUENCY_STEPS_PER_DAY, simulate_hedge
from app.simulation.monte_carlo import simulate_monte_carlo
from app.strategies.builder import StrategyLegSpec, StrategyResolutionError, analyze_strategy
from app.strategies.templates import build_template_legs

router = APIRouter()


class LegSpecIn(BaseModel):
    option_type: str
    target_abs_delta: float
    action: str
    quantity: int = 1


class SimulationRequest(BaseModel):
    symbol: str
    expiry_date: dt.date
    template_key: Optional[str] = None
    template_params: dict = {}
    legs: Optional[list[LegSpecIn]] = None
    num_days: Optional[int] = None
    rehedge_frequency: str = "daily"


class MonteCarloRequest(BaseModel):
    symbol: str
    expiry_date: dt.date
    template_key: Optional[str] = None
    template_params: dict = {}
    legs: Optional[list[LegSpecIn]] = None
    horizon_days: Optional[int] = None
    num_paths: Optional[int] = None


async def _resolve_position(body: SimulationRequest, db: AsyncSession, settings):
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
    return analysis


async def _market_context(db: AsyncSession, symbol: str, analysis, settings) -> dict:
    underlying = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if underlying is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    rv20 = await history_service.get_latest_hv(db, underlying.id, 20)
    daily_spot_vol = (rv20 or 0.15) / math.sqrt(settings.trading_days_per_year)
    leg_ivs = [leg.iv for leg in analysis.legs if leg.iv is not None]
    avg_iv = sum(leg_ivs) / len(leg_ivs) if leg_ivs else 0.15
    return {"spot0": underlying.spot_price, "daily_spot_vol": daily_spot_vol, "sigma0_vol_points": avg_iv * 100}


def _clamp_to_expiry(requested_days: int, expiry_date: dt.date) -> int:
    """A simulation can't run past the option's own expiry — clamp instead of
    silently producing a post-expiry P&L attribution that no longer means anything."""
    dte = max((expiry_date - dt.date.today()).days, 1)
    return min(requested_days, dte)


@router.post("/simulation/hedge")
async def post_hedge_simulation(body: SimulationRequest, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if body.rehedge_frequency not in FREQUENCY_STEPS_PER_DAY:
        raise HTTPException(422, f"rehedge_frequency must be one of {list(FREQUENCY_STEPS_PER_DAY)}")

    analysis = await _resolve_position(body, db, settings)
    ctx = await _market_context(db, body.symbol, analysis, settings)
    num_days = _clamp_to_expiry(body.num_days or settings.hedge_sim_default_days, body.expiry_date)

    return simulate_hedge(
        greeks=analysis.greeks, net_premium=analysis.net_premium, spot0=ctx["spot0"],
        sigma0_vol_points=ctx["sigma0_vol_points"], rate=settings.risk_free_rate, daily_spot_vol=ctx["daily_spot_vol"],
        num_days=num_days, rehedge_frequency=body.rehedge_frequency,
        hedge_cost_bps=settings.hedge_sim_cost_bps, vol_of_vol_points=settings.hedge_sim_vol_of_vol_points,
        mean_reversion=settings.hedge_sim_mean_reversion,
    )


@router.post("/simulation/monte-carlo")
async def post_monte_carlo_simulation(body: MonteCarloRequest, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    analysis = await _resolve_position(body, db, settings)
    ctx = await _market_context(db, body.symbol, analysis, settings)
    horizon_days = _clamp_to_expiry(body.horizon_days or settings.monte_carlo_default_horizon_days, body.expiry_date)

    return simulate_monte_carlo(
        greeks=analysis.greeks, net_premium=analysis.net_premium, spot0=ctx["spot0"],
        sigma0_vol_points=ctx["sigma0_vol_points"], rate=settings.risk_free_rate, daily_spot_vol=ctx["daily_spot_vol"],
        horizon_days=horizon_days, num_paths=body.num_paths or settings.monte_carlo_default_paths,
        vol_of_vol_points=settings.hedge_sim_vol_of_vol_points, mean_reversion=settings.hedge_sim_mean_reversion,
    )
