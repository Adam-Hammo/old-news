"""readings count the structure they kept

Which of an item's readings a reader is shown used to be settled by length alone, so a
page of template boilerplate beat anything a feed said in fewer words, and a feed that
had dropped the headings beat the page that kept them by a few dozen characters.

Counting headings, quotes and pictures is what lets that be decided on what a reading
kept rather than on how long it ran. Zero until the extractor sweep re-reads each row,
which the bumped rules revision already asks it to do.

Revision ID: 96f2ad0f8de3
Revises: 0618b1b711c1
Create Date: 2026-09-01 04:35:08.152271+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "96f2ad0f8de3"
down_revision: str | Sequence[str] | None = "0618b1b711c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "extractions",
        sa.Column("structure_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("extractions", "structure_count")
