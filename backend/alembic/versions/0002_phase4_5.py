"""Phase 4-5: users, backtesting, positions, alerts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(32), nullable=False),
        sa.Column("params", sa.JSON, nullable=False),
        sa.Column("summary", sa.JSON, nullable=False),
        sa.Column("regime_breakdown", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtestruns_underlying_id", "backtest_runs", ["underlying_id"])
    op.create_index("ix_backtestruns_created_at", "backtest_runs", ["created_at"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date, nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("entry_value", sa.Float, nullable=False),
        sa.Column("exit_value", sa.Float, nullable=False),
        sa.Column("entry_zscore", sa.Float, nullable=False),
        sa.Column("exit_zscore", sa.Float, nullable=False),
        sa.Column("holding_days", sa.Integer, nullable=False),
        sa.Column("gross_pnl", sa.Float, nullable=False),
        sa.Column("transaction_cost", sa.Float, nullable=False),
        sa.Column("net_pnl", sa.Float, nullable=False),
        sa.Column("regime_at_entry", sa.String(16), nullable=False),
    )
    op.create_index("ix_backtesttrades_run_id", "backtest_trades", ["run_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("expiry_id", sa.Integer, sa.ForeignKey("expiries.id"), nullable=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("legs", sa.JSON, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_open", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_positions_underlying_id", "positions", ["underlying_id"])
    op.create_index("ix_positions_opened_at", "positions", ["opened_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(32), nullable=False, server_default=""),
        sa.Column("condition", sa.String(8), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="WEB"),
        sa.Column("webhook_url", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currently_met", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_alerts_underlying_id", "alerts", ["underlying_id"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("alert_id", sa.Integer, sa.ForeignKey("alerts.id"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_value", sa.Float, nullable=False),
        sa.Column("message", sa.String(256), nullable=False),
    )
    op.create_index("ix_alertevents_alert_id", "alert_events", ["alert_id"])
    op.create_index("ix_alertevents_triggered_at", "alert_events", ["triggered_at"])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("positions")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
    op.drop_table("users")
