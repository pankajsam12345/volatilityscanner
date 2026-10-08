from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.calendar import calendar_matrix
from app.analytics.fair_value import historical_mean_fair_value
from app.analytics.no_arbitrage import check_calendar_variance
from app.analytics.relative_value import evaluate_relative_value
from app.analytics.term_structure import ForwardVolResult
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service
from app.services.volatility_service import get_all_expiry_snapshots

router = APIRouter()


@router.get("/calendar/{symbol}")
async def get_calendar_matrix(symbol: str, db: AsyncSession = Depends(get_db)):
    """Calendar Analyzer matrix (§32): every near<far expiry pair, with historical context where available."""
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    snapshots = await get_all_expiry_snapshots(db, u, settings)
    expiry_tuples = [
        (es.tenor_label, es.t_years, es.smile.atm_iv)
        for es in snapshots.values() if es.smile.atm_iv is not None
    ]

    cells = []
    for cell in calendar_matrix(expiry_tuples):
        bucket = f"{cell.near_label}_{cell.far_label}"
        spread_hist = await history_service.get_metric_history(db, u.id, "calendar_spread", bucket)
        fwd_hist = await history_service.get_metric_history(db, u.id, "forward_vol", bucket)

        fair = historical_mean_fair_value(spread_hist)
        signal = evaluate_relative_value(
            f"Calendar {bucket}", cell.calendar_spread * 100, [x * 100 for x in spread_hist],
            (fair * 100) if fair is not None else None, "historical_mean", settings.zscore_extreme_threshold,
        )
        fv_result = ForwardVolResult(
            forward_variance=(cell.forward_vol ** 2 if cell.forward_vol is not None else 0.0),
            forward_vol=cell.forward_vol, valid=cell.forward_vol_valid,
            error=None if cell.forward_vol_valid else "negative implied forward variance",
        )
        no_arb = check_calendar_variance(fv_result, cell.near_label, cell.far_label)

        cells.append({
            "near_label": cell.near_label, "far_label": cell.far_label,
            "near_iv": cell.near_iv, "far_iv": cell.far_iv, "calendar_spread": cell.calendar_spread,
            "forward_vol": cell.forward_vol, "forward_vol_valid": cell.forward_vol_valid,
            "calendar_spread_vol_pts_zscore": signal.history.zscore if signal.history else None,
            "calendar_spread_vol_pts_percentile": signal.history.percentile if signal.history else None,
            "signal": signal.signal,
            "forward_vol_history_sample_size": len(fwd_hist),
            "no_arbitrage_flag": {"passed": no_arb.passed, "detail": no_arb.detail},
        })

    return {"symbol": symbol, "cells": cells}
