"""capture backoff, feed poll log and www fallback

`feed_polls` — one row per poll, appended, and the only place a feed's history now lives.
Four columns go with it. `last_error` held the most recent failure and was overwritten by
the next poll. `consecutive_failures` was a counter maintained beside the thing it counted,
which is a second copy that can only ever disagree; it is a scalar subquery over this table
now. `suspended` and `suspended_reason` were two causes wearing one name — a 410, which is
the publisher's permanent statement and reads off the log as `Feed.gone`, and giving up
after N failures, which is our policy and now lives in `due_polls` beside the setting that
defines it. Changing that number takes effect at once instead of leaving rows stamped with
the old one. Only `failed` backs a feed off: a 304 and a robots refusal are both healthy
polls that happen to carry no items.

`hosts.requires_www` — observed, not configured. A publisher can serve its feed from `www`
and link its articles at an apex nobody gave a DNS record to, which is 15 versions in this
corpus and 301 failed fetches. Learned from the one capture that only worked with the
prefix put back, so it costs a single wasted request per host, ever.

No schema change for the capture backoff or the host breaker, which is the point: every
attempt already writes a `page_captures` row carrying its status and time, so how many
times a page has refused and when it last did are queries, not columns. A version that has
never succeeded has only failures on it, so counting rows counts consecutive failures.

Revision ID: b3022eaac306
Revises: 9798af481409
Create Date: 2026-08-19 04:17:48.832217+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3022eaac306"
down_revision: str | Sequence[str] | None = "9798af481409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feed_polls",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("feed_id", sa.UUID(), nullable=False),
        sa.Column(
            "polled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("new_items", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ok', 'not_modified', 'disallowed', 'failed')",
            name=op.f("ck_feed_polls_known_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"], ["feeds.id"], name=op.f("fk_feed_polls_feed_id_feeds"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_polls")),
    )
    op.create_index(
        "ix_feed_polls_feed_polled",
        "feed_polls",
        ["feed_id", sa.literal_column("polled_at DESC")],
        unique=False,
    )
    op.drop_index("ix_feeds_suspended", table_name="feeds")
    op.drop_column("feeds", "last_error")
    op.drop_column("feeds", "suspended")
    op.drop_column("feeds", "suspended_reason")
    op.drop_column("feeds", "consecutive_failures")
    op.add_column(
        "hosts",
        sa.Column("requires_www", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("hosts", "requires_www")
    op.add_column(
        "feeds",
        sa.Column("consecutive_failures", sa.INTEGER(), server_default="0", nullable=False),
    )
    op.add_column(
        "feeds",
        sa.Column(
            "suspended_reason", sa.TEXT(), server_default=sa.text("''::text"), nullable=False
        ),
    )
    op.add_column(
        "feeds",
        sa.Column("suspended", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("ix_feeds_suspended", "feeds", ["suspended"], unique=False)
    op.add_column(
        "feeds",
        sa.Column(
            "last_error",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.drop_index("ix_feed_polls_feed_polled", table_name="feed_polls")
    op.drop_table("feed_polls")
