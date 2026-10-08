"""initial schema + TimescaleDB hypertables

Revision ID: 0001
Revises:
Create Date: 2026-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "underlyings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("spot_price", sa.Float, nullable=False),
        sa.Column("lot_size", sa.Integer, nullable=False, server_default="1"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_underlyings_symbol", "underlyings", ["symbol"])
    op.create_index("ix_underlyings_timestamp", "underlyings", ["timestamp"])

    op.create_table(
        "expiries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=False),
        sa.Column("days_to_expiry", sa.Integer, nullable=False),
        sa.Column("business_days_to_expiry", sa.Integer, nullable=False),
    )
    op.create_index("ix_expiries_underlying_id", "expiries", ["underlying_id"])
    op.create_index("ix_expiries_expiry_date", "expiries", ["expiry_date"])

    option_type_enum = sa.Enum("CALL", "PUT", name="optiontype")

    op.create_table(
        "options",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("expiry_id", sa.Integer, sa.ForeignKey("expiries.id"), nullable=False),
        sa.Column("strike", sa.Float, nullable=False),
        sa.Column("option_type", option_type_enum, nullable=False),
        sa.Column("bid", sa.Float, nullable=False),
        sa.Column("ask", sa.Float, nullable=False),
        sa.Column("ltp", sa.Float, nullable=False),
        sa.Column("volume", sa.Integer, nullable=False, server_default="0"),
        sa.Column("open_interest", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bid_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ask_quantity", sa.Integer, nullable=False, server_default="0"),
        # `timestamp` joins the PK (composite with id) because TimescaleDB
        # requires the hypertable partitioning column in every unique index.
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="DEMO DATA"),
    )
    op.create_index("ix_options_underlying_id", "options", ["underlying_id"])
    op.create_index("ix_options_expiry_id", "options", ["expiry_id"])
    op.create_index("ix_options_strike", "options", ["strike"])
    op.create_index("ix_options_timestamp", "options", ["timestamp"])

    iv_status_enum = sa.Enum(
        "VALID", "NO_CONVERGENCE", "INVALID_PRICE", "WIDE_SPREAD",
        "ARBITRAGE_VIOLATION", "INSUFFICIENT_DATA", name="ivstatus",
    )

    op.create_table(
        "volatility_snapshots",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("expiry_id", sa.Integer, sa.ForeignKey("expiries.id"), nullable=False),
        sa.Column("strike", sa.Float, nullable=False),
        sa.Column("option_type", option_type_enum, nullable=False),
        sa.Column("iv", sa.Float, nullable=True),
        sa.Column("iv_status", iv_status_enum, nullable=False),
        sa.Column("iv_error", sa.String(256), nullable=True),
        sa.Column("delta", sa.Float, nullable=True),
        sa.Column("gamma", sa.Float, nullable=True),
        sa.Column("vega", sa.Float, nullable=True),
        sa.Column("theta", sa.Float, nullable=True),
        sa.Column("rho", sa.Float, nullable=True),
        sa.Column("vanna", sa.Float, nullable=True),
        sa.Column("volga", sa.Float, nullable=True),
        sa.Column("charm", sa.Float, nullable=True),
        sa.Column("speed", sa.Float, nullable=True),
        sa.Column("color", sa.Float, nullable=True),
        sa.Column("zomma", sa.Float, nullable=True),
        sa.Column("data_quality", sa.String(32), nullable=False, server_default="GOOD"),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True, nullable=False),
    )
    op.create_index("ix_volsnap_underlying_id", "volatility_snapshots", ["underlying_id"])
    op.create_index("ix_volsnap_expiry_id", "volatility_snapshots", ["expiry_id"])
    op.create_index("ix_volsnap_strike", "volatility_snapshots", ["strike"])
    op.create_index("ix_volsnap_timestamp", "volatility_snapshots", ["timestamp"])

    vol_estimator_enum = sa.Enum(
        "CLOSE_CLOSE", "PARKINSON", "GARMAN_KLASS", "ROGERS_SATCHELL",
        "YANG_ZHANG", "EWMA", name="volestimator",
    )

    op.create_table(
        "historical_volatility",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("estimator", vol_estimator_enum, nullable=False, server_default="CLOSE_CLOSE"),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column("hv_5", sa.Float, nullable=True),
        sa.Column("hv_10", sa.Float, nullable=True),
        sa.Column("hv_20", sa.Float, nullable=True),
        sa.Column("hv_30", sa.Float, nullable=True),
        sa.Column("hv_60", sa.Float, nullable=True),
        sa.Column("hv_90", sa.Float, nullable=True),
        sa.Column("hv_252", sa.Float, nullable=True),
    )
    op.create_index("ix_hv_underlying_id", "historical_volatility", ["underlying_id"])
    op.create_index("ix_hv_timestamp", "historical_volatility", ["timestamp"])

    op.create_table(
        "metric_history",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(32), nullable=False, server_default=""),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True, nullable=False),
    )
    op.create_index("ix_metrichist_underlying_id", "metric_history", ["underlying_id"])
    op.create_index("ix_metrichist_metric_name", "metric_history", ["metric_name"])
    op.create_index("ix_metrichist_bucket", "metric_history", ["bucket"])
    op.create_index("ix_metrichist_timestamp", "metric_history", ["timestamp"])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("underlying_id", sa.Integer, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("expiry_id", sa.Integer, sa.ForeignKey("expiries.id"), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(32), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("score_components", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("gross_edge", sa.Float, nullable=False),
        sa.Column("transaction_cost", sa.Float, nullable=False),
        sa.Column("net_edge", sa.Float, nullable=False),
        sa.Column("max_risk", sa.Float, nullable=False),
        sa.Column("expected_return", sa.Float, nullable=False),
        sa.Column("risk_reward", sa.Float, nullable=False),
        sa.Column("liquidity_status", sa.String(16), nullable=False),
        sa.Column("data_quality", sa.String(32), nullable=False, server_default="GOOD"),
        sa.Column("legs", sa.JSON, nullable=False),
        sa.Column("greeks", sa.JSON, nullable=False),
        sa.Column("historical_context", sa.JSON, nullable=False),
        sa.Column("no_arbitrage_flags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("explanation", sa.JSON, nullable=False),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_opp_underlying_id", "opportunities", ["underlying_id"])
    op.create_index("ix_opp_expiry_id", "opportunities", ["expiry_id"])
    op.create_index("ix_opp_timestamp", "opportunities", ["timestamp"])

    # TimescaleDB hypertables for the genuinely time-series tables.
    # migrate_data=>true lets this run even if rows already exist.
    for table in ("options", "volatility_snapshots", "historical_volatility", "metric_history"):
        op.execute(
            f"SELECT create_hypertable('{table}', 'timestamp', "
            f"if_not_exists => TRUE, migrate_data => TRUE)"
        )


def downgrade() -> None:
    op.drop_table("opportunities")
    op.drop_table("metric_history")
    op.drop_table("historical_volatility")
    op.drop_table("volatility_snapshots")
    op.drop_table("options")
    op.drop_table("expiries")
    op.drop_table("underlyings")
    op.execute("DROP TYPE IF EXISTS volestimator")
    op.execute("DROP TYPE IF EXISTS ivstatus")
    op.execute("DROP TYPE IF EXISTS optiontype")
