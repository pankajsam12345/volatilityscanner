from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.regime import classify_regime
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service

router = APIRouter()


@router.get("/underlyings")
async def list_underlyings(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    rows = (await db.execute(select(Underlying))).scalars().all()
    out = []
    for u in rows:
        rv20 = await history_service.get_latest_hv(db, u.id, 20)
        atm_1m = await history_service.get_metric_history(db, u.id, "atm_iv", "1M")
        atm_iv = atm_1m[-1] if atm_1m else None

        rv_series = await history_service.get_hv_series(db, u.id, 20, "CLOSE_CLOSE")
        rv_history = [v for _, v in rv_series if v is not None]
        regime = classify_regime(
            rv_history[-1], rv_history[:-1], settings.regime_low_percentile,
            settings.regime_high_percentile, settings.regime_extreme_percentile,
        ).regime if rv_history else "UNKNOWN"

        out.append({
            "symbol": u.symbol, "exchange": u.exchange, "spot_price": u.spot_price,
            "lot_size": u.lot_size, "timestamp": u.timestamp, "is_demo": u.is_demo,
            "atm_iv_1m": atm_iv, "rv20": rv20, "regime": regime,
            "iv_rv_spread": (atm_iv - rv20) if (atm_iv is not None and rv20 is not None) else None,
        })
    return out


@router.get("/underlyings/{symbol}")
async def get_underlying(symbol: str, db: AsyncSession = Depends(get_db)):
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")
    rv20 = await history_service.get_latest_hv(db, u.id, 20)
    return {
        "symbol": u.symbol, "exchange": u.exchange, "spot_price": u.spot_price,
        "lot_size": u.lot_size, "timestamp": u.timestamp, "is_demo": u.is_demo, "rv20": rv20,
    }
