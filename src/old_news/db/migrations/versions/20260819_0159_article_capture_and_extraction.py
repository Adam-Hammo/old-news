"""article capture and extraction

Everything the article side of the archive needs, in one revision because it is one change.

`page_captures` — the bytes behind an article, kept whole. Extraction output never lands
here: this is what the network said, and what we made of it is derived, disposable and its
own table, so a wrong extractor costs a rerun rather than the article. Append-only and
deliberately not unique on the version: a 403 on Tuesday and the page on Friday are both
facts, "the capture" is the latest successful row, and that bounds a retry without ever
updating anything. `host_id` is a foreign key rather than a host re-derived from the URL at
read time — that is exactly how `feeds.host` used to drift.

`extractions` and `extraction_images` — derived, versioned on which item version the text
came from and which extractor made it. Re-extracting with the same extractor rewrites its
own row; a new extractor version lands alongside. Kept off `item_versions` deliberately:
that table is append-only and describes what a feed document said, so hanging derived
fields on it would mean updating it. The quality columns are the point as much as the body
is — the failure that matters is cheerfully extracting a cookie banner and marking it done.

`image_captures` — images are the largest line in the archive and the only one that neither
compresses nor has a natural bound, so the lead image is fetched unasked and the rest wait
to be asked for. Keyed on the URL digest and the bytes together: on the digest because an
image URL can exceed what btree will take, and on the bytes as well because a re-crop lands
on the same path and keying on the URL alone would conflate two images and keep the older.

`training_rules` — the first filter, and the shape every later one reuses: a dimension, a
case-insensitive substring, and a scope that is global when `feed_id` is null. Only the
blocking tier exists; thumbs and their integer weights land here later. The dimension and
source constraints follow the enums, so a rule that could never match cannot be stored.

Indexes are the queries, not the columns. A unique constraint's leading column already
serves lookups on it, so there is no separate index for `extractions.item_version_id`,
`extraction_images.extraction_id` or `image_captures.url_digest`. What the constraints
cannot serve gets its own: `(extractor, extractor_version)` for "which versions has this
extractor not done", and a partial index on `extraction_images.role` limited to slots with
nothing fetched, which keeps it small as the archive fills.

Revision ID: 9798af481409
Revises: b95f8f8afdbf
Create Date: 2026-08-19 01:59:32.297481+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9798af481409"
down_revision: str | Sequence[str] | None = "b95f8f8afdbf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "image_captures",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_digest", sa.LargeBinary(), nullable=False),
        sa.Column("host_id", sa.UUID(), nullable=False),
        sa.Column("final_url", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_type", sa.String(length=64), server_default="", nullable=False),
        sa.Column("body_hash", sa.LargeBinary(), nullable=False),
        sa.Column("body", sa.LargeBinary(), server_default=sa.text("''::bytea"), nullable=False),
        sa.Column("byte_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"], name=op.f("fk_image_captures_host_id_hosts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_image_captures")),
        sa.UniqueConstraint(
            "url_digest", "body_hash", name=op.f("uq_image_captures_url_digest_body_hash")
        ),
    )
    op.create_index(op.f("ix_image_captures_host_id"), "image_captures", ["host_id"], unique=False)
    op.create_table(
        "training_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("blocks", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("feed_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimension IN ('title_phrase', 'url_pattern')",
            name=op.f("ck_training_rules_known_dimension"),
        ),
        sa.CheckConstraint(
            "source IN ('seed', 'hand', 'observed')", name=op.f("ck_training_rules_known_source")
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feeds.id"],
            name=op.f("fk_training_rules_feed_id_feeds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_rules")),
        sa.UniqueConstraint(
            "dimension",
            "pattern",
            "feed_id",
            name=op.f("uq_training_rules_dimension_pattern_feed_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_training_rules_feed_id"), "training_rules", ["feed_id"], unique=False)
    op.create_table(
        "page_captures",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("item_version_id", sa.UUID(), nullable=False),
        sa.Column("host_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("body_hash", sa.LargeBinary(), nullable=False),
        sa.Column("body", sa.LargeBinary(), server_default=sa.text("''::bytea"), nullable=False),
        sa.Column("dictionary_id", sa.UUID(), nullable=True),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["dictionary_id"],
            ["zstd_dictionaries.id"],
            name=op.f("fk_page_captures_dictionary_id_zstd_dictionaries"),
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"], name=op.f("fk_page_captures_host_id_hosts")
        ),
        sa.ForeignKeyConstraint(
            ["item_version_id"],
            ["item_versions.id"],
            name=op.f("fk_page_captures_item_version_id_item_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_captures")),
    )
    op.create_index(
        op.f("ix_page_captures_dictionary_id"), "page_captures", ["dictionary_id"], unique=False
    )
    op.create_index(op.f("ix_page_captures_host_id"), "page_captures", ["host_id"], unique=False)
    op.create_index(
        "ix_page_captures_succeeded",
        "page_captures",
        ["item_version_id"],
        unique=False,
        postgresql_where=sa.text("status BETWEEN 200 AND 299"),
    )
    op.create_index(
        "ix_page_captures_url_body", "page_captures", ["url", "body_hash"], unique=False
    )
    op.create_index(
        "ix_page_captures_version_fetched",
        "page_captures",
        ["item_version_id", sa.literal_column("fetched_at DESC")],
        unique=False,
    )
    op.create_table(
        "extractions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("item_version_id", sa.UUID(), nullable=False),
        sa.Column("page_capture_id", sa.UUID(), nullable=False),
        sa.Column("extractor", sa.String(length=32), nullable=False),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("byline", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.String(length=32), server_default="", nullable=False),
        sa.Column("site_name", sa.Text(), server_default="", nullable=False),
        sa.Column("page_type", sa.String(length=32), server_default="", nullable=False),
        sa.Column("published_claim", sa.String(length=32), server_default="", nullable=False),
        sa.Column(
            "links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paragraph_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("link_density", sa.Float(), server_default="0", nullable=False),
        sa.Column("feed_body_ratio", sa.Float(), server_default="0", nullable=False),
        sa.Column("ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["item_version_id"],
            ["item_versions.id"],
            name=op.f("fk_extractions_item_version_id_item_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_capture_id"],
            ["page_captures.id"],
            name=op.f("fk_extractions_page_capture_id_page_captures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extractions")),
        sa.UniqueConstraint(
            "item_version_id",
            "extractor",
            "extractor_version",
            name=op.f("uq_extractions_item_version_id_extractor_extractor_version"),
        ),
    )
    op.create_index(
        "ix_extractions_extractor", "extractions", ["extractor", "extractor_version"], unique=False
    )
    op.create_index(
        op.f("ix_extractions_page_capture_id"), "extractions", ["page_capture_id"], unique=False
    )
    op.create_table(
        "extraction_images",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("extraction_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("image_capture_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("alt", sa.Text(), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "role IN ('lead', 'body')", name=op.f("ck_extraction_images_known_role")
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extractions.id"],
            name=op.f("fk_extraction_images_extraction_id_extractions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_capture_id"],
            ["image_captures.id"],
            name=op.f("fk_extraction_images_image_capture_id_image_captures"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_images")),
        sa.UniqueConstraint(
            "extraction_id", "url", name=op.f("uq_extraction_images_extraction_id_url")
        ),
    )
    op.create_index(
        op.f("ix_extraction_images_image_capture_id"),
        "extraction_images",
        ["image_capture_id"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_images_wanted",
        "extraction_images",
        ["role"],
        unique=False,
        postgresql_where=sa.text("image_capture_id IS NULL"),
    )

    # Scoped to the publishers whose conventions they are, not global: `/live/` in a path
    # means a live blog at the Guardian and could mean anything elsewhere. Attached by feed
    # URL, so a database following neither publisher gets no rules and a fresh install
    # starts with none.
    op.execute(
        """
        INSERT INTO training_rules (dimension, pattern, blocks, feed_id, source, note)
        SELECT 'url_pattern', '/live/', true, id, 'seed',
               'Live blogs. Guardian marks them in the path.'
        FROM feeds WHERE url LIKE '%theguardian.com%'
        """
    )
    op.execute(
        """
        INSERT INTO training_rules (dimension, pattern, blocks, feed_id, source, note)
        SELECT 'title_phrase', 'live:', true, id, 'seed',
               'Live blogs. ABC marks them in the title.'
        FROM feeds WHERE url LIKE '%abc.net.au%'
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_extraction_images_wanted",
        table_name="extraction_images",
        postgresql_where=sa.text("image_capture_id IS NULL"),
    )
    op.drop_index(op.f("ix_extraction_images_image_capture_id"), table_name="extraction_images")
    op.drop_table("extraction_images")
    op.drop_index(op.f("ix_extractions_page_capture_id"), table_name="extractions")
    op.drop_index("ix_extractions_extractor", table_name="extractions")
    op.drop_table("extractions")
    op.drop_index("ix_page_captures_version_fetched", table_name="page_captures")
    op.drop_index("ix_page_captures_url_body", table_name="page_captures")
    op.drop_index(
        "ix_page_captures_succeeded",
        table_name="page_captures",
        postgresql_where=sa.text("status BETWEEN 200 AND 299"),
    )
    op.drop_index(op.f("ix_page_captures_host_id"), table_name="page_captures")
    op.drop_index(op.f("ix_page_captures_dictionary_id"), table_name="page_captures")
    op.drop_table("page_captures")
    op.drop_index(op.f("ix_training_rules_feed_id"), table_name="training_rules")
    op.drop_table("training_rules")
    op.drop_index(op.f("ix_image_captures_host_id"), table_name="image_captures")
    op.drop_table("image_captures")
