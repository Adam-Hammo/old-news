"""capture outcomes recorded not inferred

`page_captures.outcome` — what a visit turned out to be, written rather than worked back
out of a status code. The status alone cannot say the difference that matters: a 403 the
publisher sent and a fetch we decided not to send both used to be absent-or-non-2xx, so
the sweep choosing what to capture could not tell a page it had already been refused from
one it had never asked for. It chose the same twenty-five doomed versions every minute
for three hours.

Three decisions now record a row where they used to return silently — robots forbidding
the path, robots never having been read, and the host breaker being shut. None of them
counts as the publisher failing, so `outcome` is also what keeps them from moving the
breaker that made the third: only `failed` is counted and only `ok` clears the count,
and everything else is stepped over.

That replaces the per-URL status list the breaker carried in Python. A 404 is `gone`,
which is a fact about a link and not about a publisher, and it says so in the column
instead of in a `frozenset` two packages away.

Backfilled from status, which is exactly the inference being retired — it is right for
every row that exists, because until now a row only ever meant a request was sent.

Revision ID: b0acf7d96d8b
Revises: db3ab8609d07
Create Date: 2026-08-20 06:38:58.353184+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0acf7d96d8b"
down_revision: str | Sequence[str] | None = "db3ab8609d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("page_captures", sa.Column("outcome", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE page_captures
           SET outcome = CASE
                             WHEN status BETWEEN 200 AND 299 THEN 'ok'
                             WHEN status IN (404, 410) THEN 'gone'
                             ELSE 'failed'
                         END
        """
    )
    op.alter_column("page_captures", "outcome", nullable=False)
    op.create_check_constraint(
        op.f("ck_page_captures_known_capture_outcome"),
        "page_captures",
        "outcome IN ('ok', 'gone', 'failed', 'disallowed', 'refused', 'unknown_rules')",
    )
    # Counting a host's failures back to its last success reads this, newest first.
    op.create_index(
        "ix_page_captures_host_fetched",
        "page_captures",
        ["host_id", sa.literal_column("fetched_at DESC"), "outcome"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_page_captures_host_fetched", table_name="page_captures")
    op.drop_constraint(
        op.f("ck_page_captures_known_capture_outcome"), "page_captures", type_="check"
    )
    op.drop_column("page_captures", "outcome")
