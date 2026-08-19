"""count refusals per capture policy

A refusal is a fact about how we asked as much as about the publisher, and the way we ask
changes. `page_captures.capture_policy` records which way, and the capture sweep counts
only the attempts made the way it asks now — so improving the asking forgives what came
before it without deleting a row. Same bargain `extractions.extractor_version` already
makes, rather than a second mechanism for the same idea.

The first instance is the `www.` retry. theclimatebrink links its own articles at an apex
nobody gave a DNS record to, so 15 versions burned through the retry limit while we were
asking a name that could never answer, and the fix could not reach the articles it was
written for. Existing rows default to policy 1 and the code now sends 2, which brings them
back with no data migration and no `UPDATE`.

Medium's ten come back too and will refuse again, which is correct: nothing here knows the
difference between a publisher who blocks us and one we were asking wrongly. The host
breaker bounds that to one probe an interval.

Revision ID: ad58c563664a
Revises: b3022eaac306
Create Date: 2026-08-19 23:15:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ad58c563664a"
down_revision: str | Sequence[str] | None = "b3022eaac306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "page_captures",
        sa.Column("capture_policy", sa.String(length=16), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("page_captures", "capture_policy")
