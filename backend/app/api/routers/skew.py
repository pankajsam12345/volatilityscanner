from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


@router.get("/skew/{symbol}")
async def get_skew(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    snapshots = await get_all_expiry_snapshots(db, u, settings)
    expiries = []
    for es in sorted(snapshots.values(), key=lambda e: e.t_years):
        buckets = []
        for d in settings.rr_bf_deltas:
            put_wing, call_wing, skew_val = es.skew.get(f"put_wing_{d}"), es.skew.get(f"call_wing_{d}"), es.skew.get(f"skew_{d}")
            put_wing_ctx = await metric_with_context(db, u.id, f"skew_{d}", es.tenor_label, put_wing)
            buckets.append({
                "delta": d, "put_iv": es.grid.get(f"put_{d}d_iv"), "call_iv": es.grid.get(f"call_{d}d_iv"),
                "put_wing": put_wing, "call_wing": call_wing, "put_call_skew": skew_val, "put_wing_history": put_wing_ctx,
            })
        expiries.append({
            "expiry_date": es.expiry_date, "tenor_label": es.tenor_label, "atm_iv": es.smile.atm_iv, "buckets": buckets,
        })

    return {"symbol": symbol, "expiries": expiries}
