"""Expiry.source: distinguish LIVE ladder rows from HISTORICAL_REPLAY rows

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23

Fixes a real data-correctness bug: without this column, the chain-replay
backtester's historical rolling-expiry rows (scripts/seed.py,
chain_replay.py) were indistinguishable from today's live expiry ladder in
every "list this symbol's expiries" query (volatility_service
.get_all_expiry_snapshots, option_chain.py's expiries endpoint,
opportunity_service's expiry loop). Their negative days_to_expiry always
minimizes nearest_tenor_label's distance to the smallest tenor (7 days), so
every historical replay expiry silently surfaced as a bogus "1W" entry
dated years in the past. Existing rows default to LIVE on upgrade — this is
a best-effort backfill; re-seeding (scripts/seed.py) is what actually
produces correctly-tagged rows going forward.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expiries", sa.Column("source", sa.String(20), nullable=False, server_default="LIVE"))


def downgrade() -> None:
    op.drop_column("expiries", "source")
