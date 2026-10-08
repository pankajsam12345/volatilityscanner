from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.no_arbitrage import check_butterfly_convexity
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


@router.get("/butterfly/{symbol}")
async def get_butterfly(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    snapshots = await get_all_expiry_snapshots(db, u, settings)
    expiries = []
    for es in sorted(snapshots.values(), key=lambda e: e.t_years):
        buckets = []
        for d in settings.rr_bf_deltas:
            bf_val = es.bf.get(f"bf_{d}")
            ctx = await metric_with_context(db, u.id, f"bf_{d}", es.tenor_label, bf_val)
            convexity = check_butterfly_convexity(bf_val, str(d))
            buckets.append({"delta": d, "bf": bf_val, "history": ctx, "convexity_flag": {"passed": convexity.passed, "detail": convexity.detail}})
        expiries.append({"expiry_date": es.expiry_date, "tenor_label": es.tenor_label, "atm_iv": es.smile.atm_iv, "buckets": buckets})

    return {"symbol": symbol, "expiries": expiries}
