from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


@router.get("/risk-reversal/{symbol}")
async def get_risk_reversal(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    snapshots = await get_all_expiry_snapshots(db, u, settings)
    expiries = []
    for es in sorted(snapshots.values(), key=lambda e: e.t_years):
        buckets = []
        for d in settings.rr_bf_deltas:
            rr_val = es.rr.get(f"rr_{d}")
            ctx = await metric_with_context(db, u.id, f"rr_{d}", es.tenor_label, rr_val)
            buckets.append({"delta": d, "rr": rr_val, "history": ctx})
        expiries.append({"expiry_date": es.expiry_date, "tenor_label": es.tenor_label, "buckets": buckets})

    return {"symbol": symbol, "expiries": expiries}
