"""Alert channels: recipient column for EMAIL/TELEGRAM delivery

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("recipient", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "recipient")