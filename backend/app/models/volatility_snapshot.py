import datetime as dt
import enum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.option import OptionType


class IVStatus(str, enum.Enum):
    VALID = "VALID"
    NO_CONVERGENCE = "NO_CONVERGENCE"
    INVALID_PRICE = "INVALID_PRICE"
    WIDE_SPREAD = "WIDE_SPREAD"
    ARBITRAGE_VIOLATION = "ARBITRAGE_VIOLATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilitySnapshot(Base):
    __tablename__ = "volatility_snapshots"

    # Composite PK (id, timestamp): required for TimescaleDB hypertable partitioning.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    expiry_id: Mapped[int] = mapped_column(ForeignKey("expiries.id"), index=True)
    strike: Mapped[float] = mapped_column(Float, index=True)
    option_type: Mapped[OptionType] = mapped_column(Enum(OptionType))

    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_status: Mapped[IVStatus] = mapped_column(Enum(IVStatus))
    iv_error: Mapped[str | None] = mapped_column(String(256), nullable=True)

    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    rho: Mapped[float | None] = mapped_column(Float, nullable=True)
    vanna: Mapped[float | None] = mapped_column(Float, nullable=True)
    volga: Mapped[float | None] = mapped_column(Float, nullable=True)
    charm: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[float | None] = mapped_column(Float, nullable=True)
    zomma: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_quality: Mapped[str] = mapped_column(String(32), default="GOOD")
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
