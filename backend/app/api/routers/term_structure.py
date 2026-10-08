from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.term_structure import classify_regime, detect_local_inversions, forward_vol, term_structure_curvature, term_structure_slope
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


@router.get("/term-structure/{symbol}")
async def get_term_structure(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    all_snapshots = await get_all_expiry_snapshots(db, u, settings)
    snapshots = sorted(all_snapshots.values(), key=lambda e: e.t_years)
    points = [(es.t_years, es.smile.atm_iv) for es in snapshots if es.smile.atm_iv is not None]

    curve = []
    prev = None
    for es in snapshots:
        if es.smile.atm_iv is None:
            continue
        fwd = None
        if prev is not None and es.t_years > prev.t_years:
            fv = forward_vol(prev.smile.atm_iv, prev.t_years, es.smile.atm_iv, es.t_years)
            fwd = {"value": fv.forward_vol, "valid": fv.valid, "error": fv.error}
        atm_ctx = await metric_with_context(db, u.id, "atm_iv", es.tenor_label, es.smile.atm_iv)
        curve.append({
            "expiry_date": es.expiry_date, "tenor_label": es.tenor_label, "days_to_expiry": round(es.t_years * 365),
            "atm_iv": es.smile.atm_iv, "atm_iv_history": atm_ctx, "forward_vol_from_prev": fwd,
        })
        prev = es

    return {
        "symbol": symbol,
        "regime": classify_regime(points) if len(points) >= 2 else None,
        "slope": term_structure_slope(points),
        "curvature": term_structure_curvature(points),
        "local_inversions_at_tenor_years": detect_local_inversions(points) if len(points) >= 3 else [],
        "curve": curve,
    }
