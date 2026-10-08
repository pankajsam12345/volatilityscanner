"""
Periodic background jobs (§3/§54). Refresh pulls a fresh chain through the
real IV-solver pipeline (app.services.snapshot_service); recompute then
re-scores opportunities against that fresh chain plus the historical
distributions seeded by scripts/seed.py.

Known limitation: this does NOT append today's close to the historical
MetricHistory/HistoricalVolatility distributions — that's an end-of-day
job intentionally out of scope for this build (see README "Known
Limitations"). Re-running scripts/seed.py refreshes the historical window.
"""
from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.market_data.provider_factory import get_market_data_provider
from app.services.alert_service import check_all_alerts
from app.services.opportunity_service import generate_opportunities
from app.services.snapshot_service import refresh_underlying
from app.tasks.celery_app import celery_app


async def _refresh_all_snapshots() -> None:
    settings = get_settings()
    provider = get_market_data_provider()
    async with AsyncSessionLocal() as session:
        for symbol in settings.demo_symbols:
            await refresh_underlying(session, provider, symbol, settings)


async def _recompute_all_opportunities() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        for symbol in settings.demo_symbols:
            await generate_opportunities(session, symbol, settings)


@celery_app.task(name="app.tasks.jobs.refresh_all_snapshots")
def refresh_all_snapshots() -> None:
    asyncio.run(_refresh_all_snapshots())


@celery_app.task(name="app.tasks.jobs.recompute_all_opportunities")
def recompute_all_opportunities() -> None:
    asyncio.run(_recompute_all_opportunities())


async def _check_alerts() -> None:
    async with AsyncSessionLocal() as session:
        await check_all_alerts(session)


@celery_app.task(name="app.tasks.jobs.check_alerts")
def check_alerts() -> None:
    asyncio.run(_check_alerts())
