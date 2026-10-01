"""filters, not training

Training is off the roadmap, and what was built of it was only ever the blocking tier: a
row that keeps a matching item out of capture, the river and Kindle. That is a filter, so
the table is called one and loses the parts that were waiting for thumbs. `blocks` goes
because every remaining row blocks, and `observed` leaves the source constraint because
nothing ever derived a rule.

A rename rather than the drop and create autogenerate offers, so the seeded live-blog
filters and anything added by hand survive. A row with `blocks` false did nothing and would
start blocking once the column is gone, so it is deleted first.

An empty pattern is now refused by the database. Every title contains the empty string, so
one such row would have blocked the whole feed, or everything.

Revision ID: 227cc3d66c53
Revises: c3d9f021b796
Create Date: 2026-10-01 00:44:33.214874+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "227cc3d66c53"
down_revision: str | Sequence[str] | None = "c3d9f021b796"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMED = (
    ("pk_training_rules", "pk_filters"),
    ("fk_training_rules_feed_id_feeds", "fk_filters_feed_id_feeds"),
    ("uq_training_rules_dimension_pattern_feed_id", "uq_filters_dimension_pattern_feed_id"),
    ("ck_training_rules_known_dimension", "ck_filters_known_dimension"),
    # Postgres 18 names its not-null constraints after the table they were made on.
    *(
        (f"training_rules_{column}_not_null", f"filters_{column}_not_null")
        for column in ("id", "dimension", "pattern", "source", "note", "created_at")
    ),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("delete from training_rules where not blocks")
    op.drop_column("training_rules", "blocks")
    op.drop_constraint(op.f("ck_training_rules_known_source"), "training_rules", type_="check")
    op.rename_table("training_rules", "filters")
    for old, new in RENAMED:
        op.execute(f"alter table filters rename constraint {old} to {new}")
    op.execute("alter index ix_training_rules_feed_id rename to ix_filters_feed_id")
    op.create_check_constraint(
        op.f("ck_filters_known_source"), "filters", "source IN ('seed', 'hand')"
    )
    op.create_check_constraint(op.f("ck_filters_pattern_not_empty"), "filters", "pattern <> ''")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_filters_pattern_not_empty"), "filters", type_="check")
    op.drop_constraint(op.f("ck_filters_known_source"), "filters", type_="check")
    op.execute("alter index ix_filters_feed_id rename to ix_training_rules_feed_id")
    for old, new in RENAMED:
        op.execute(f"alter table filters rename constraint {new} to {old}")
    op.rename_table("filters", "training_rules")
    op.create_check_constraint(
        op.f("ck_training_rules_known_source"),
        "training_rules",
        "source IN ('seed', 'hand', 'observed')",
    )
    # Every surviving row blocks, so they are filled as blocking and new ones default not to.
    op.add_column(
        "training_rules",
        sa.Column("blocks", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.alter_column("training_rules", "blocks", server_default=sa.text("false"))
