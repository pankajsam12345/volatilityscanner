from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.regime import classify_regime
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Underlying
from app.services import history_service

router = APIRouter()


@router.get("/regime/{symbol}")
async def get_regime(symbol: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")

    rv_series = await history_service.get_hv_series(db, u.id, 20, "CLOSE_CLOSE")
    history = [v for _, v in rv_series if v is not None]
    current = history[-1] if history else None
    if current is None:
        raise HTTPException(404, f"No RV20 history for '{symbol}'")

    result = classify_regime(
        current, history[:-1],  # compare "today" against everything strictly before it
        settings.regime_low_percentile, settings.regime_high_percentile, settings.regime_extreme_percentile,
    )
    return {
        "symbol": symbol, "regime": result.regime, "rv20_current": result.current,
        "rv20_percentile": result.percentile, "rv20_zscore": result.zscore,
        "sample_size": result.history.sample_size if result.history else 0,
    }
