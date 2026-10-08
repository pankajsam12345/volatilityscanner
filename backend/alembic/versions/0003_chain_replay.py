"""Chain-replay backtest: replay_mode on backtest_runs, legs on backtest_trades

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("replay_mode", sa.String(16), nullable=False, server_default="SIGNAL"))
    op.add_column("backtest_trades", sa.Column("legs", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_trades", "legs")
    op.drop_column("backtest_runs", "replay_mode")
