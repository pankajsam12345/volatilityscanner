from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service

router = APIRouter()


@router.get("/realized-vol/{symbol}")
async def get_realized_vol(symbol: str, estimator: str = Query("CLOSE_CLOSE"), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    latest = {}
    series = {}
    for w in settings.hv_windows:
        rows = await history_service.get_hv_series(db, u.id, w, estimator)
        series[f"hv_{w}"] = [{"timestamp": ts, "value": v} for ts, v in rows if v is not None]
        latest[f"hv_{w}"] = rows[-1][1] if rows else None

    return {"symbol": symbol, "estimator": estimator, "latest": latest, "series": series}
