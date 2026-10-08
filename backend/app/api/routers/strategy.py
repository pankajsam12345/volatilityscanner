import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.strategies.builder import StrategyAnalysis, StrategyLegSpec, StrategyResolutionError, analyze_strategy
from app.strategies.templates import build_template_legs, list_templates

router = APIRouter()


@router.get("/strategy/templates")
async def get_templates():
    return list_templates()


class LegSpecIn(BaseModel):
    option_type: str
    target_abs_delta: float
    action: str
    quantity: int = 1


class AnalyzeRequest(BaseModel):
    symbol: str
    expiry_date: dt.date
    template_key: Optional[str] = None
    template_params: dict = {}
    legs: Optional[list[LegSpecIn]] = None


def _analysis_to_dict(a: StrategyAnalysis) -> dict:
    return {
        "symbol": a.symbol, "expiry_date": a.expiry_date,
        "legs": [leg.as_dict() for leg in a.legs],
        "net_premium": a.net_premium, "greeks": a.greeks,
        "transaction_cost_cash": a.transaction_cost_cash,
        "payoff_curve": [{"spot": s, "pnl": p} for s, p in a.payoff_curve],
        "breakevens": a.breakevens, "max_risk": a.max_risk, "max_reward": a.max_reward,
        "undefined_risk": a.undefined_risk, "undefined_reward": a.undefined_reward,
    }


@router.post("/strategy/analyze")
async def post_analyze(body: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
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

    return _analysis_to_dict(analysis)
