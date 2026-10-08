import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Expiry, Underlying
from app.services.volatility_service import build_expiry_snapshot

router = APIRouter()


async def _get_underlying(db: AsyncSession, symbol: str) -> Underlying:
    u = (await db.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"Unknown symbol '{symbol}'")
    return u


@router.get("/option-chain/{symbol}/expiries")
async def list_expiries(symbol: str, db: AsyncSession = Depends(get_db)):
    u = await _get_underlying(db, symbol)
    rows = (
        await db.execute(
            select(Expiry).where(Expiry.underlying_id == u.id, Expiry.source == "LIVE").order_by(Expiry.days_to_expiry)
        )
    ).scalars().all()
    return [
        {"expiry_date": r.expiry_date, "days_to_expiry": r.days_to_expiry, "business_days_to_expiry": r.business_days_to_expiry}
        for r in rows
    ]


@router.get("/option-chain/{symbol}")
async def get_option_chain(symbol: str, expiry: dt.date = Query(...), db: AsyncSession = Depends(get_db)):
    from app.core.config import get_settings

    u = await _get_underlying(db, symbol)
    settings = get_settings()
    expiry_row = (
        await db.execute(select(Expiry).where(Expiry.underlying_id == u.id, Expiry.expiry_date == expiry, Expiry.source == "LIVE"))
    ).scalar_one_or_none()
    if expiry_row is None:
        raise HTTPException(404, f"No expiry {expiry} for '{symbol}'")

    es = await build_expiry_snapshot(db, u, expiry_row, settings)
    if es is None:
        raise HTTPException(404, f"No option chain data for '{symbol}' {expiry}")

    strikes = sorted({strike for strike, _ in es.snapshot_by_key})
    atm_strike = min(strikes, key=lambda k: abs(k - u.spot_price)) if strikes else None

    rows = []
    for strike in strikes:
        row = {"strike": strike, "is_atm": strike == atm_strike}
        for side, key in (("call", "CALL"), ("put", "PUT")):
            snap = es.snapshot_by_key.get((strike, key))
            opt = es.option_by_key.get((strike, key))
            if snap is None or opt is None:
                row[side] = None
                continue
            spread_pct = (opt.ask - opt.bid) / ((opt.ask + opt.bid) / 2) * 100 if (opt.ask + opt.bid) > 0 else None
            row[side] = {
                "bid": opt.bid, "ask": opt.ask, "ltp": opt.ltp, "volume": opt.volume, "open_interest": opt.open_interest,
                "iv": snap.iv, "iv_status": snap.iv_status.value, "delta": snap.delta, "gamma": snap.gamma,
                "vega": snap.vega, "theta": snap.theta, "unusual_spread": spread_pct is not None and spread_pct > settings.max_bid_ask_spread_pct,
            }
        rows.append(row)

    return {
        "symbol": symbol, "spot_price": u.spot_price, "expiry_date": expiry, "timestamp": es.timestamp,
        "atm_iv": es.smile.atm_iv, "rows": rows,
    }
