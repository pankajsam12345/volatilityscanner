import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BacktestRun(Base):
    """A single backtest configuration + its summary stats (§36-37)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlyings.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(32))  # IV_RV | CALENDAR | SKEW | RR | BF | FORWARD_VOL
    bucket: Mapped[str] = mapped_column(String(32))  # tenor label, or "near_far" for calendar/forward vol
    params: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    regime_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    replay_mode: Mapped[str] = mapped_column(String(16), default="SIGNAL")  # SIGNAL | CHAIN
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class BacktestTrade(Base):
    """One simulated round-trip trade within a BacktestRun."""

    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)

    entry_date: Mapped[dt.date] = mapped_column(Date)
    exit_date: Mapped[dt.date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(16))  # SHORT | LONG
    entry_value: Mapped[float] = mapped_column(Float)
    exit_value: Mapped[float] = mapped_column(Float)
    entry_zscore: Mapped[float] = mapped_column(Float)
    exit_zscore: Mapped[float] = mapped_column(Float)
    holding_days: Mapped[int] = mapped_column(Integer)
    gross_pnl: Mapped[float] = mapped_column(Float)
    transaction_cost: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float)
    regime_at_entry: Mapped[str] = mapped_column(String(16))
    legs: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # per-leg entry/exit detail, CHAIN replay_mode only
