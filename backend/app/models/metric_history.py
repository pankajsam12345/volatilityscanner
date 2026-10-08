import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MetricHistory(Base):
    """
    Generic daily time series for any volatility metric that needs historical
    context (§18): ATM IV, IV-RV spread, IV/RV ratio, skew25/10, RR25/10,
    BF25/10, calendar spread per expiry-bucket pair, forward vol, term
    structure slope/curvature. One row per (underlying, metric_name,
    bucket, day). `bucket` disambiguates e.g. which expiry or expiry-pair
    the metric belongs to (e.g. "1M", "1M_3M"); empty string if not applicable.
    """

    __tablename__ = "metric_history"

    # Composite PK (id, timestamp): required for TimescaleDB hypertable partitioning.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(32), default="", index=True)
    value: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
