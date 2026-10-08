from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service
from app.services.volatility_service import get_all_expiry_snapshots, metric_with_context

router = APIRouter()


async def _get_underlying(db: AsyncSession, symbol: str) -> Underlying:
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")
    return u


@router.get("/volatility/{symbol}")
async def get_volatility_summary(symbol: str, db: AsyncSession = Depends(get_db)):
    """IV-RV dashboard (§8/§30): ATM IV per expiry vs RV, with historical context."""
    settings = get_settings()
    u = await _get_underlying(db, symbol)
    snapshots = await get_all_expiry_snapshots(db, u, settings)

    rv_series = {w: await history_service.get_latest_hv(db, u.id, w) for w in settings.hv_windows}

    expiries = []
    for es in sorted(snapshots.values(), key=lambda e: e.t_years):
        atm_ctx = await metric_with_context(db, u.id, "atm_iv", es.tenor_label, es.smile.atm_iv)
        iv_rv_spread = (es.smile.atm_iv - rv_series[20]) if (es.smile.atm_iv is not None and rv_series.get(20) is not None) else None
        expiries.append({
            "expiry_date": es.expiry_date, "tenor_label": es.tenor_label, "days_to_expiry": round(es.t_years * 365),
            "atm_iv": es.smile.atm_iv, "atm_iv_history": atm_ctx,
            "iv_rv_20_spread": iv_rv_spread,
            "iv_rv_20_ratio": (es.smile.atm_iv / rv_series[20]) if (es.smile.atm_iv and rv_series.get(20)) else None,
        })

    return {"symbol": symbol, "spot_price": u.spot_price, "realized_vol": rv_series, "expiries": expiries}
