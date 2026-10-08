import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Alert(Base):
    """A user-configured alert rule (§42)."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    metric: Mapped[str] = mapped_column(String(32))  # e.g. atm_iv, iv_rv_zscore, rr_25, bf_25, skew_25, calendar_spread
    bucket: Mapped[str] = mapped_column(String(32), default="")  # tenor label, or near_far bucket
    condition: Mapped[str] = mapped_column(String(8))  # ">" | "<"
    threshold: Mapped[float] = mapped_column(Float)
    channel: Mapped[str] = mapped_column(String(16), default="WEB")  # WEB | WEBHOOK | EMAIL | TELEGRAM
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(256), nullable=True)  # EMAIL address or TELEGRAM chat_id
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currently_met: Mapped[bool] = mapped_column(Boolean, default=False)


class AlertEvent(Base):
    """A fired instance of an Alert."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    triggered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_value: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(256))
