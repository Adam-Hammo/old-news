"""compression dictionaries

Bodies from one feed are near-identical poll to poll, so a trained zstd dictionary
roughly halves what a document costs. A dictionary is immutable and must outlive being
the current one, because every body compressed against it stays that way — hence many
rows per scope, and a foreign key from `documents` that refuses to let one be dropped
while bodies still need it.

`dict_id` is a hash of the content, so it is unique per scope rather than globally: a
retrain that finds nothing new produces the same dictionary, which is a no-op and not an
error. NULLS NOT DISTINCT because exactly one of the two scope columns is ever set.

Nothing is rewritten. A zstd frame names its own dictionary, so bodies written before
this revision keep reading exactly as they did.

Revision ID: b95f8f8afdbf
Revises: f08d0d17d77f
Create Date: 2026-08-19 00:20:05.184411+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b95f8f8afdbf"
down_revision: str | Sequence[str] | None = "f08d0d17d77f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "zstd_dictionaries",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("dict_id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.UUID(), nullable=True),
        sa.Column("host_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("sample_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(feed_id IS NULL) <> (host_id IS NULL)", name=op.f("ck_zstd_dictionaries_one_scope")
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feeds.id"],
            name=op.f("fk_zstd_dictionaries_feed_id_feeds"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["host_id"],
            ["hosts.id"],
            name=op.f("fk_zstd_dictionaries_host_id_hosts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zstd_dictionaries")),
        sa.UniqueConstraint(
            "dict_id",
            "feed_id",
            "host_id",
            name=op.f("uq_zstd_dictionaries_dict_id_feed_id_host_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_zstd_dictionaries_feed_id"), "zstd_dictionaries", ["feed_id"], unique=False
    )
    op.create_index(
        op.f("ix_zstd_dictionaries_host_id"), "zstd_dictionaries", ["host_id"], unique=False
    )
    op.add_column("documents", sa.Column("dictionary_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_documents_dictionary_id"), "documents", ["dictionary_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_documents_dictionary_id_zstd_dictionaries"),
        "documents",
        "zstd_dictionaries",
        ["dictionary_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_documents_dictionary_id_zstd_dictionaries"), "documents", type_="foreignkey"
    )
    op.drop_index(op.f("ix_documents_dictionary_id"), table_name="documents")
    op.drop_column("documents", "dictionary_id")
    op.drop_index(op.f("ix_zstd_dictionaries_host_id"), table_name="zstd_dictionaries")
    op.drop_index(op.f("ix_zstd_dictionaries_feed_id"), table_name="zstd_dictionaries")
    op.drop_table("zstd_dictionaries")
