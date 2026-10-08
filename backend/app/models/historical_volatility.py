import datetime as dt
import enum

from sqlalchemy import DateTime, Enum, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VolEstimator(str, enum.Enum):
    CLOSE_CLOSE = "CLOSE_CLOSE"
    PARKINSON = "PARKINSON"
    GARMAN_KLASS = "GARMAN_KLASS"
    ROGERS_SATCHELL = "ROGERS_SATCHELL"
    YANG_ZHANG = "YANG_ZHANG"
    EWMA = "EWMA"


class HistoricalVolatility(Base):
    __tablename__ = "historical_volatility"

    # Composite PK (id, timestamp): required for TimescaleDB hypertable partitioning.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    estimator: Mapped[VolEstimator] = mapped_column(Enum(VolEstimator), default=VolEstimator.CLOSE_CLOSE)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    hv_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_30: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_60: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_252: Mapped[float | None] = mapped_column(Float, nullable=True)
