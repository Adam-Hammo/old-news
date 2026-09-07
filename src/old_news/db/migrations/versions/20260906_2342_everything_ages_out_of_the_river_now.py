"""everything ages out of the river now

Null used to mean a feed nothing ages out of, and it was what every subscription started
as. That made the river a second archive with a worse contents page: the only way to stop
a feed accumulating forever was to remember to set a window by hand, and a feed nobody got
round to never stopped growing. Keeping a thing is the archive's job, so the window is now
a bound on the river rather than an opinion about the feed, and thirty days is the longest
one there is.

The backfill runs before the NOT NULL because there is no default to fill it with yet, and
it clamps as well as fills: the screen used to offer six weeks and six months, and both are
past the ceiling the route now enforces. A subscription already inside it keeps what it has.

Revision ID: c3d9f021b796
Revises: 49e46b633183
Create Date: 2026-09-06 23:42:30.324411+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d9f021b796"
down_revision: str | Sequence[str] | None = "49e46b633183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONGEST = "interval '30 days'"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        update subscriptions
           set expires_after = {LONGEST}
         where expires_after is null
            or expires_after > {LONGEST}
        """
    )
    op.alter_column(
        "subscriptions",
        "expires_after",
        existing_type=postgresql.INTERVAL(),
        server_default=sa.text(LONGEST),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "subscriptions",
        "expires_after",
        existing_type=postgresql.INTERVAL(),
        server_default=None,
        nullable=True,
    )
