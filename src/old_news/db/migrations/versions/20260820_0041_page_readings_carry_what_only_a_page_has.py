"""page readings carry what only a page has

`extractions` was holding four kinds of thing: provenance, content, measurements of that
content, and a verdict on those measurements. Only one of those was wrong, but it was
enough to make the table look like it needed subclasses.

Six claim columns and `page_capture_id` move to `page_extractions`, a joined-table child
keyed on the parent. A feed reading is a base row and nothing else, so no column on
`extractions` is meaningless for half its rows, and the check constraint tying
`page_capture_id` to `source` goes — it existed only to hand-roll the invariant that
inheritance states structurally. `source` is now a real discriminator.

`ok` and `note` are deleted rather than moved. They were a verdict against
`min_body_chars` and `min_paragraphs`, which live in config, so a stored answer is wrong
the moment either changes and says nothing about it — 25 of 1058 rows were already
carrying one. Same reason `feeds.suspended` went: a threshold judgement belongs where the
threshold is. The measurements stay, because unlike a verdict they are pure functions of
`body` and cannot go stale.

`feed_body_ratio` is deleted too. It only ever existed because the feed reading was not a
row you could join to. Both are rows now, so the ratio is
`page.char_count / feed.char_count` across two rows of one table — a query, not a column.

Revision ID: db3ab8609d07
Revises: fc9498f53fff
Create Date: 2026-08-20 00:41:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "db3ab8609d07"
down_revision: str | Sequence[str] | None = "fc9498f53fff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLAIMS = ["title", "byline", "language", "site_name", "page_type", "published_claim"]


def upgrade() -> None:
    op.create_table(
        "page_extractions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("page_capture_id", sa.UUID(), nullable=False),
        *(sa.Column(name, sa.Text(), server_default="", nullable=False) for name in CLAIMS[:2]),
        sa.Column("language", sa.String(length=32), server_default="", nullable=False),
        sa.Column("site_name", sa.Text(), server_default="", nullable=False),
        sa.Column("page_type", sa.String(length=32), server_default="", nullable=False),
        sa.Column("published_claim", sa.String(length=32), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["id"],
            ["extractions.id"],
            name=op.f("fk_page_extractions_id_extractions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_capture_id"],
            ["page_captures.id"],
            name=op.f("fk_page_extractions_page_capture_id_page_captures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_extractions")),
    )
    op.create_index(
        op.f("ix_page_extractions_page_capture_id"), "page_extractions", ["page_capture_id"]
    )

    columns = ", ".join(CLAIMS)
    op.execute(
        f"INSERT INTO page_extractions (id, page_capture_id, {columns}) "
        f"SELECT id, page_capture_id, {columns} FROM extractions WHERE source = 'page'"
    )

    op.drop_constraint("capture_matches_source", "extractions", type_="check")
    op.drop_index("ix_extractions_page_capture_id", table_name="extractions")
    for name in ("page_capture_id", *CLAIMS, "feed_body_ratio", "ok", "note"):
        op.drop_column("extractions", name)


def downgrade() -> None:
    op.add_column("extractions", sa.Column("page_capture_id", sa.UUID(), nullable=True))
    for name in ("title", "byline", "site_name"):
        op.add_column("extractions", sa.Column(name, sa.TEXT(), server_default="", nullable=False))
    for name, size in (("language", 32), ("page_type", 32), ("published_claim", 32)):
        op.add_column(
            "extractions",
            sa.Column(name, sa.String(length=size), server_default="", nullable=False),
        )
    op.add_column(
        "extractions",
        sa.Column("feed_body_ratio", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "extractions",
        sa.Column("ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("extractions", sa.Column("note", sa.TEXT(), server_default="", nullable=False))

    assignments = ", ".join(f"{name} = p.{name}" for name in CLAIMS)
    op.execute(
        "UPDATE extractions e SET page_capture_id = p.page_capture_id, "
        f"{assignments} FROM page_extractions p WHERE p.id = e.id"
    )
    # The verdict and the ratio cannot be reconstructed: one needed thresholds that were
    # never stored beside it, the other needed a feed reading that had no row.
    op.drop_index(op.f("ix_page_extractions_page_capture_id"), table_name="page_extractions")
    op.drop_table("page_extractions")

    op.create_index("ix_extractions_page_capture_id", "extractions", ["page_capture_id"])
    op.create_foreign_key(
        op.f("fk_extractions_page_capture_id_page_captures"),
        "extractions",
        "page_captures",
        ["page_capture_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "capture_matches_source",
        "extractions",
        "(source = 'page') = (page_capture_id IS NOT NULL)",
    )
