from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.calendar import calendar_matrix
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


@router.get("/forward-vol/{symbol}")
async def get_forward_vol(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    snapshots = await get_all_expiry_snapshots(db, u, settings)
    expiry_tuples = [(es.tenor_label, es.t_years, es.smile.atm_iv) for es in snapshots.values() if es.smile.atm_iv is not None]

    out = []
    for cell in calendar_matrix(expiry_tuples):
        bucket = f"{cell.near_label}_{cell.far_label}"
        ctx = await metric_with_context(db, u.id, "forward_vol", bucket, cell.forward_vol)
        out.append({
            "near_label": cell.near_label, "far_label": cell.far_label,
            "spot_vol_far": cell.far_iv, "forward_vol": cell.forward_vol, "valid": cell.forward_vol_valid,
            "history": ctx,
        })

    return {"symbol": symbol, "forward_vol_pairs": out}
