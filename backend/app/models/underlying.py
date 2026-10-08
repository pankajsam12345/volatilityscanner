import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Underlying(Base):
    __tablename__ = "underlyings"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    exchange: Mapped[str] = mapped_column(String(32))
    spot_price: Mapped[float] = mapped_column(Float)
    lot_size: Mapped[int] = mapped_column(default=1)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    # MockProvider's per-tenor DailySurface state (atm_vol/skew_b/curvature_c),
    # persisted so the live Celery refresh can evolve_surface() forward from
    # where it last left off instead of reinitializing from scratch — see
    # market_data/mock_provider.py and README known limitations.
    surface_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
