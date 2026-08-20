"""item versions stop holding text

`content` and `summary` were the last two columns on the core table holding a body, and
the only ones anywhere holding one uncompressed. The previous revision copied every
version's text into `feed_captures`, so this one only has to stop keeping a second copy.

Its own revision because it is the destructive half. Both apply in one `upgrade head` and
that is safe — the copy runs first, in the same chain — but the reason a column can go is
worth being able to read on its own, and reverting the drop without reverting the table
that replaced it has to be one step.

Nothing user-facing read either column: neither appears in admin, `reading_body` now
compares two extractions rather than a reading against a raw column, and search will index
`extractions.body`. `content_hash` is unaffected — `fingerprint_of` hashes the parsed item
in memory at ingest, never these columns, so change detection and identity do not notice.

The downgrade restores the columns empty. `feed_captures.body` is zstd, sometimes against a
dictionary, and no amount of SQL will decompress it; the text is not lost, it is one sweep
away, and inventing a half-restore that only worked for the rows nothing had re-carved yet
would be worse than an honest blank. `page_readings` set the precedent when `ok` and
`feed_body_ratio` went.

Revision ID: c4f1b6de20a7
Revises: a0010d3fcfaa
Create Date: 2026-08-20 13:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f1b6de20a7"
down_revision: str | Sequence[str] | None = "a0010d3fcfaa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("item_versions", "summary")
    op.drop_column("item_versions", "content")


def downgrade() -> None:
    """Downgrade schema."""
    for name in ("content", "summary"):
        op.add_column(
            "item_versions",
            sa.Column(name, sa.TEXT(), server_default=sa.text("''::text"), nullable=False),
        )
