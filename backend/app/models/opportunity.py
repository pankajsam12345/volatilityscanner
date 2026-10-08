import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Opportunity(Base):
    """Persisted output of the relative-value opportunity pipeline (§54)."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    expiry_id: Mapped[int | None] = mapped_column(ForeignKey("expiries.id"), nullable=True, index=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

    strategy: Mapped[str] = mapped_column(String(64))  # e.g. "CALENDAR", "RISK_REVERSAL"
    signal_type: Mapped[str] = mapped_column(String(64))  # e.g. "IV_RV", "CALENDAR_SPREAD"
    direction: Mapped[str] = mapped_column(String(32))  # e.g. "SHORT_1M_LONG_3M_VOL"

    score: Mapped[float] = mapped_column(Float)
    score_components: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)

    gross_edge: Mapped[float] = mapped_column(Float)
    transaction_cost: Mapped[float] = mapped_column(Float)
    net_edge: Mapped[float] = mapped_column(Float)

    max_risk: Mapped[float] = mapped_column(Float)
    expected_return: Mapped[float] = mapped_column(Float)
    risk_reward: Mapped[float] = mapped_column(Float)

    liquidity_status: Mapped[str] = mapped_column(String(16))
    data_quality: Mapped[str] = mapped_column(String(32), default="GOOD")

    legs: Mapped[list] = mapped_column(JSON)
    greeks: Mapped[dict] = mapped_column(JSON)
    historical_context: Mapped[dict] = mapped_column(JSON)
    no_arbitrage_flags: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[dict] = mapped_column(JSON)  # {"why": [...], "risks": [...]}

    is_demo: Mapped[bool] = mapped_column(default=True)
