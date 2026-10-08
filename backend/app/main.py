import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, install_error_handlers
from app.core.rate_limit import install_rate_limiting
from app.api.routers import (
    alerts,
    auth,
    backtest,
    butterfly,
    calendar as calendar_router,
    forward_vol,
    opportunities,
    option_chain,
    portfolio,
    realized_vol,
    regime,
    risk_reversal,
    settings as settings_router,
    simulation,
    skew,
    strategy,
    term_structure,
    underlyings,
    volatility,
)

configure_logging()
settings = get_settings()

app = FastAPI(
    title="Volatility Opportunity Scanner",
    description=(
        "Relative-value volatility opportunity engine. All figures are "
        "model-based estimates against DEMO DATA unless a live market data "
        "provider is configured. Nothing here is a guarantee of profit."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
install_error_handlers(app)
install_rate_limiting(app)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(underlyings.router, prefix="/api", tags=["underlyings"])
app.include_router(option_chain.router, prefix="/api", tags=["option-chain"])
app.include_router(volatility.router, prefix="/api", tags=["volatility"])
app.include_router(term_structure.router, prefix="/api", tags=["term-structure"])
app.include_router(skew.router, prefix="/api", tags=["skew"])
app.include_router(risk_reversal.router, prefix="/api", tags=["risk-reversal"])
app.include_router(butterfly.router, prefix="/api", tags=["butterfly"])
app.include_router(calendar_router.router, prefix="/api", tags=["calendar"])
app.include_router(forward_vol.router, prefix="/api", tags=["forward-vol"])
app.include_router(realized_vol.router, prefix="/api", tags=["realized-vol"])
app.include_router(regime.router, prefix="/api", tags=["regime"])
app.include_router(opportunities.router, prefix="/api", tags=["opportunities"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])
app.include_router(strategy.router, prefix="/api", tags=["strategy"])
app.include_router(backtest.router, prefix="/api", tags=["backtest"])
app.include_router(simulation.router, prefix="/api", tags=["simulation"])
app.include_router(portfolio.router, prefix="/api", tags=["portfolio"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])


@app.get("/api/health")
async def health():
    """Deprecated alias for /api/healthz, kept for backwards compatibility."""
    return {"status": "ok"}


@app.get("/api/healthz")
async def healthz():
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/api/readyz")
async def readyz():
    """Readiness: the process can actually serve traffic (DB + Redis reachable)."""
    checks = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"

    try:
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
