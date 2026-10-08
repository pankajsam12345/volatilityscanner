import datetime as dt

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Expiry(Base):
    __tablename__ = "expiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    expiry_date: Mapped[dt.date] = mapped_column(Date, index=True)
    days_to_expiry: Mapped[int] = mapped_column(Integer)
    business_days_to_expiry: Mapped[int] = mapped_column(Integer)
    # LIVE: part of today's real multi-expiry ladder (Option Chain, Scanner,
    # Volatility/Term Structure/Skew/etc. pages). HISTORICAL_REPLAY: the
    # chain-replay backtester's single rolling near-month expiry per
    # historical day (scripts/seed.py, chain_replay.py) — excluded from
    # every live-page query so a years-old rolled expiry can't get
    # mislabeled "1W" and show up next to today's real data (days_to_expiry
    # is negative for these, which nearest_tenor_label has no sane bucket
    # for).
    source: Mapped[str] = mapped_column(String(20), default="LIVE")
