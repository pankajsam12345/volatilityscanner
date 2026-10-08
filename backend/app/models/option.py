import datetime as dt
import enum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OptionType(str, enum.Enum):
    CALL = "CALL"
    PUT = "PUT"


class Option(Base):
    __tablename__ = "options"

    # Composite PK (id, timestamp): TimescaleDB requires the partitioning
    # (hypertable) column to be part of every unique/primary-key index.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    expiry_id: Mapped[int] = mapped_column(ForeignKey("expiries.id"), index=True)
    strike: Mapped[float] = mapped_column(Float, index=True)
    option_type: Mapped[OptionType] = mapped_column(Enum(OptionType))
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    ltp: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    open_interest: Mapped[int] = mapped_column(Integer, default=0)
    bid_quantity: Mapped[int] = mapped_column(Integer, default=0)
    ask_quantity: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="DEMO DATA")
