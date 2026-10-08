"""
Live refresh path: MarketDataProvider -> clean -> IV solver -> Greeks ->
persist (§54's real, per-tick pipeline — as opposed to scripts/seed.py's
one-time analytic shortcut used purely to backfill historical distributions).
Used by the Celery periodic task and the manual /refresh API endpoint.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.black_scholes import BSInputs
from app.analytics.black_scholes import delta as bs_delta, gamma as bs_gamma, rho as bs_rho, theta as bs_theta, vega as bs_vega
from app.analytics.greeks import charm, color, speed, vanna, volga, zomma
from app.analytics.iv_solver import IVStatus, solve_iv
from app.market_data.base import MarketDataProvider
from app.market_data.mock_provider import MockProvider
from app.models import Expiry, Option, Underlying, VolatilitySnapshot


def _sync_mock_surface(provider: MarketDataProvider, symbol: str, underlying: Underlying | None) -> None:
    """
    MockProvider-only continuity fix: resume from the last persisted surface
    checkpoint and evolve_surface() forward to today, instead of serving
    whatever `init_surface` baseline the provider singleton happened to be
    constructed with — see mock_provider.sync_surface/advance_to and README
    known limitations ("daily discontinuity").
    """
    if not isinstance(provider, MockProvider):
        return
    if underlying is not None and underlying.surface_state:
        provider.sync_surface(symbol, underlying.timestamp.date(), underlying.spot_price, underlying.surface_state)
    provider.advance_to(symbol, dt.date.today())


async def refresh_underlying(session: AsyncSession, provider: MarketDataProvider, symbol: str, settings) -> int:
    existing = (await session.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    _sync_mock_surface(provider, symbol, existing)

    quote = await provider.get_underlying_quote(symbol)
    rate = await provider.get_interest_rates()
    dividend_yield = await provider.get_dividends(symbol)

    underlying = existing
    if underlying is None:
        underlying = Underlying(
            symbol=symbol, exchange=quote.exchange, spot_price=quote.spot_price,
            lot_size=quote.lot_size, timestamp=quote.timestamp, is_demo=quote.is_demo,
        )
        session.add(underlying)
        await session.flush()
    else:
        underlying.spot_price = quote.spot_price
        underlying.timestamp = quote.timestamp

    if isinstance(provider, MockProvider):
        _, _, tenor_state = provider.export_surface(symbol)
        underlying.surface_state = tenor_state

    for expiry_info in await provider.get_expiries(symbol):
        expiry_row = (
            await session.execute(
                select(Expiry).where(Expiry.underlying_id == underlying.id, Expiry.expiry_date == expiry_info.expiry_date)
            )
        ).scalar_one_or_none()
        if expiry_row is None:
            expiry_row = Expiry(
                underlying_id=underlying.id, expiry_date=expiry_info.expiry_date,
                days_to_expiry=expiry_info.days_to_expiry, business_days_to_expiry=expiry_info.business_days_to_expiry,
                source="LIVE",
            )
            session.add(expiry_row)
            await session.flush()
        else:
            expiry_row.days_to_expiry = expiry_info.days_to_expiry
            expiry_row.business_days_to_expiry = expiry_info.business_days_to_expiry
            expiry_row.source = "LIVE"  # self-heals the rare case where this date previously only existed as a HISTORICAL_REPLAY row

        t_years = max(expiry_info.days_to_expiry, 1) / 365.0
        for oq in await provider.get_option_chain(symbol, expiry_info.expiry_date):
            session.add(Option(
                underlying_id=underlying.id, expiry_id=expiry_row.id, strike=oq.strike, option_type=oq.option_type,
                bid=oq.bid, ask=oq.ask, ltp=oq.ltp, volume=oq.volume, open_interest=oq.open_interest,
                bid_quantity=oq.bid_quantity, ask_quantity=oq.ask_quantity, timestamp=oq.timestamp, source=oq.source,
            ))

            mid = (oq.bid + oq.ask) / 2
            iv_result = solve_iv(
                market_price=mid, spot=quote.spot_price, strike=oq.strike, time_to_expiry=t_years,
                rate=rate, dividend_yield=dividend_yield, option_type=oq.option_type, bid=oq.bid, ask=oq.ask,
            )
            snap = VolatilitySnapshot(
                underlying_id=underlying.id, expiry_id=expiry_row.id, strike=oq.strike, option_type=oq.option_type,
                iv=iv_result.iv, iv_status=iv_result.status.value, iv_error=iv_result.error, timestamp=oq.timestamp,
                data_quality="GOOD" if iv_result.status == IVStatus.VALID else "MISSING_IV",
            )
            if iv_result.status == IVStatus.VALID:
                inputs = BSInputs(quote.spot_price, oq.strike, t_years, rate, dividend_yield, iv_result.iv, oq.option_type)
                snap.delta, snap.gamma, snap.vega = bs_delta(inputs), bs_gamma(inputs), bs_vega(inputs)
                snap.theta, snap.rho = bs_theta(inputs) / 365.0, bs_rho(inputs)
                snap.vanna, snap.volga = vanna(inputs), volga(inputs)
                snap.charm, snap.speed, snap.color, snap.zomma = charm(inputs) / 365.0, speed(inputs), color(inputs) / 365.0, zomma(inputs)
            session.add(snap)

    await session.commit()
    return underlying.id
