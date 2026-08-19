"""count refusals from when the host name was learned

`hosts.requires_www` becomes `hosts.www_learned_at`. It still says the same thing by being
non-null — fetch this publisher on the `www.` name — but the timestamp is also the line
before which a refusal stops counting.

Without that, the fix for a publisher whose apex has no DNS record could never reach the
articles it was for. theclimatebrink.com links its own articles at an apex nobody gave a
record to; 15 versions each failed enough times to be given up on permanently, and the
`www.` retry that would have worked only runs on a version the sweep still selects. The
learned timestamp forgives every attempt made while we were asking the wrong name, so
those 15 come back the moment any one article on the host teaches us the right one.

Written once and never moved, or the same failures would be forgiven repeatedly and the
retries would never stop. Dropped rather than migrated: one row held a value, and the
timestamp it should have had is not recoverable from a boolean.

Revision ID: a20c081aabc0
Revises: b3022eaac306
Create Date: 2026-08-19 23:05:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a20c081aabc0"
down_revision: str | Sequence[str] | None = "b3022eaac306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("www_learned_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("hosts", "requires_www")


def downgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("requires_www", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
    )
    op.drop_column("hosts", "www_learned_at")
