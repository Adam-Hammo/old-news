"""currents expiry, a subscription's tier, finished articles and the issue ledger

Expiry hangs off the subscription rather than the section it is filed under. The section
split is coarse and measured to be wrong — publishing rates put two of the three on top
of each other — so it will get reorganised, and a window attached to a category name
would be orphaned the moment one is renamed. An interval rather than a count of seconds,
so the cutoff is `now() - expires_after` and Postgres does the arithmetic against the
leading column of the river's index. Null is a feed nothing ages out of, which is what
every row starts as: nothing disappears until a window is set by hand.

`finished_at` sits beside `read_at` because opened and read are two different facts
wearing one word. Opened is a tap on a headline; finished is the bottom of the article.
Only the second is evidence of having read the thing, and it is the one an issue must
not carry again — excluding on merely opened would disqualify the case the Kindle is
for, which is skimming two paragraphs and deciding it deserves proper attention.

`tier` is how much trouble a feed is worth, and the levels nest: the wire is skimmed and
gone, an archive feed is kept properly and so every picture it carries is worth holding,
and a kindle feed is an archive feed that also goes in the book. One ordered column
rather than two booleans, so `kindle` without `archive` cannot be written at all. It is
separate from the window because the Guardian wants six hours and ABC wants a day and
both are wire, and separate from the section because the section is a display filter that
will get reorganised. Every row starts at `wire`, which is the cheap end: no body images
are fetched and no book is built until a feed is promoted by hand.

`issues` keeps the bytes it sent. Send to Kindle answers a bad book and a bad night at
Amazon with the same undocumented error and no detail, so posting the identical book a
second time is the only diagnosis available. `issue_items` is the ledger that stops an
article going out twice; it is indexed on the item because that is the question asked of
it, and the unique constraint leads on the issue.

Revision ID: b7102d4a694e
Revises: 96f2ad0f8de3
Create Date: 2026-09-04 02:05:22.441031+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7102d4a694e"
down_revision: str | Sequence[str] | None = "96f2ad0f8de3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "issues",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("subject", sa.Text(), server_default="", nullable=False),
        sa.Column("body", sa.LargeBinary(), server_default=sa.text("''::bytea"), nullable=False),
        sa.Column("byte_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
    )
    op.create_table(
        "issue_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("section", sa.Text(), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_issue_items_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_issue_items_item_id_items"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_items")),
        sa.UniqueConstraint("issue_id", "item_id", name=op.f("uq_issue_items_issue_id_item_id")),
    )
    op.create_index(op.f("ix_issue_items_item_id"), "issue_items", ["item_id"], unique=False)
    op.add_column("items", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("expires_after", sa.Interval(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("tier", sa.String(length=8), server_default="wire", nullable=False),
    )
    op.create_index(op.f("ix_subscriptions_tier"), "subscriptions", ["tier"], unique=False)
    op.create_check_constraint(
        "known_tier", "subscriptions", "tier IN ('wire', 'archive', 'kindle')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_subscriptions_known_tier"), "subscriptions", type_="check")
    op.drop_index(op.f("ix_subscriptions_tier"), table_name="subscriptions")
    op.drop_column("subscriptions", "tier")
    op.drop_column("subscriptions", "expires_after")
    op.drop_column("items", "finished_at")
    op.drop_index(op.f("ix_issue_items_item_id"), table_name="issue_items")
    op.drop_table("issue_items")
    op.drop_table("issues")
