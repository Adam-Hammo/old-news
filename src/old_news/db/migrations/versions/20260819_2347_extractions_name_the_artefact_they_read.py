"""extractions name the artefact they read

Feed text and page text are the same kind of thing — a reading of stored bytes the network
handed over — and were stored in two different shapes. The feed's sat inline on
`item_versions` with no record of what parsed it; the page's was a derived, disposable,
versioned row that said exactly what made it. That asymmetry is why "which one do I read,
index, embed" had no clean answer: the two were not comparable objects.

`extractions.source` makes them one. Both are rows, both stamped with the extractor that
produced them, both rebuildable. `item_versions.content` is untouched — it is still what
the feed document said, append-only and authoritative — and a feed-sourced extraction is
derived from it, the same way a page-sourced one is derived from a capture.

`page_capture_id` becomes nullable, because a feed extraction has no capture to name. Its
artefact is the document behind `item_version_id`, which the version already records;
repeating it here would be a second copy of `item_versions.document_id` to drift against.
A check constraint ties the two so neither shape can be stored wrong.

Existing rows are all page-sourced and are backfilled as such. The default is dropped
afterwards: leaving it would mean a caller that forgot to say silently claimed to have
read a page.

Revision ID: fc9498f53fff
Revises: ad58c563664a
Create Date: 2026-08-19 23:40:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fc9498f53fff"
down_revision: str | Sequence[str] | None = "ad58c563664a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIQUE_OLD = "uq_extractions_item_version_id_extractor_extractor_version"
# The convention template runs to 65 characters and Postgres truncates at 63.
UNIQUE_NEW = "uq_extractions_version_source_extractor"


def upgrade() -> None:
    op.add_column(
        "extractions",
        sa.Column("source", sa.String(length=8), server_default="page", nullable=False),
    )
    op.alter_column("extractions", "source", server_default=None)
    op.alter_column("extractions", "page_capture_id", existing_type=sa.UUID(), nullable=True)

    op.drop_constraint(UNIQUE_OLD, "extractions", type_="unique")
    op.create_unique_constraint(
        UNIQUE_NEW, "extractions", ["item_version_id", "source", "extractor", "extractor_version"]
    )
    op.create_check_constraint("known_source", "extractions", "source IN ('feed', 'page')")
    op.create_check_constraint(
        "capture_matches_source",
        "extractions",
        "(source = 'page') = (page_capture_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Bare suffix: the `ck` naming template interpolates whatever it is given, so the
    # full name here would be dropped as `ck_extractions_ck_extractions_…`.
    op.drop_constraint("capture_matches_source", "extractions", type_="check")
    op.drop_constraint("known_source", "extractions", type_="check")
    op.drop_constraint(UNIQUE_NEW, "extractions", type_="unique")

    # Feed-sourced rows cannot exist without the column that distinguishes them, and they
    # are rebuildable from `item_versions.content` whenever the column comes back.
    op.execute("DELETE FROM extractions WHERE source = 'feed'")
    op.create_unique_constraint(
        UNIQUE_OLD, "extractions", ["item_version_id", "extractor", "extractor_version"]
    )
    op.alter_column("extractions", "page_capture_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("extractions", "source")
