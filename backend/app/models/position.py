import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Position(Base):
    """A saved strategy (from the Strategy Builder) held in the demo portfolio (§39)."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    expiry_id: Mapped[int | None] = mapped_column(ForeignKey("expiries.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(128))
    legs: Mapped[list] = mapped_column(JSON)  # resolved legs: strike, option_type, action, quantity, iv, greeks
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_open: Mapped[bool] = mapped_column(default=True)
