"""Surface continuity: surface_state on underlyings for MockProvider day-to-day evolution

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("underlyings", sa.Column("surface_state", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("underlyings", "surface_state")
