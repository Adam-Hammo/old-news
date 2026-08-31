"""the river pages on first seen

The river orders on `first_seen_at DESC, id DESC` and pages with a keyset cursor on the
same pair. The single-column index it replaces cannot serve the tiebreak, and the
tiebreak is not an edge case: `first_seen_at` defaults to CURRENT_TIMESTAMP, which is the
transaction's, so every item one poll wrote shares a timestamp to the microsecond.

Revision ID: 0618b1b711c1
Revises: 8b1e4a90c7d2
Create Date: 2026-08-31 01:54:09.202710+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0618b1b711c1"
down_revision: str | Sequence[str] | None = "8b1e4a90c7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f("ix_items_first_seen_at"), table_name="items")
    op.create_index(
        "ix_items_river",
        "items",
        [sa.literal_column("first_seen_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_items_river", table_name="items")
    op.create_index(op.f("ix_items_first_seen_at"), "items", ["first_seen_at"], unique=False)
