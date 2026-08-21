"""feed text becomes a capture

`page_extractions` names the artefact it read; `feed_extractions` had nothing to name, so
the feed's text sat inline on `item_versions` — uncompressed, and with no record of what
parsed it out of the document. `feed_captures` is the missing artefact: one row per
version, the text `_body()` chose, compressed, stamped with the parse that chose it.

It is a materialisation, not a network event. The raw archive is `documents.body` and the
fetch that produced it is already recorded, so there is no status, host, error or outcome
here. What there is instead is `parser_version` — the provenance `documents.parse_ok`
admits it lacks in its own comment and does not supply — which is what makes re-carving
after a feedparser bump a sweep rather than a one-way loss.

Unique on the version *and* the hash. Nothing updates an append-only table, so a re-carve
has to be able to insert; identical bytes conflict and only the stamp moves, which is what
lets the sweep drain instead of offering the same document every two minutes forever. Same
bargain `image_captures` makes with `(url_digest, body_hash)`.

The text is copied across uncompressed and stamped `unknown`, because nothing recorded
which feedparser wrote it. `db/bytes.py` reads a body that never had a zstd frame the same
way it reads one that does, so those rows are readable immediately; the sweep re-carves
them against the current parser in its own time and the stamp stops being a lie.

`documents.final_url` comes along because a re-parse has to resolve relative entry links
against the URL the document was *served* from. A feed that redirects and names no
`<channel><link>` re-reads to different identities otherwise, and every version of it
carves to nothing — `page_captures.final_url` has carried exactly this since it existed.

`feed_extractions` gains a table for the same reason: a reading of a capture can name it.
Any feed reading whose version carried no text is deleted rather than left parentless —
they are derived and rebuildable, which is the whole point of the table.

Three dictionary scopes, not two. Whole feed XML and the HTML fragments inside it share a
feed and share nothing else, so `(dict_id, feed_id, host_id)` could not tell them apart.
Reusing the document dictionary would work and would leave most of the win unclaimed.

Two index corrections while in here. `ix_page_captures_succeeded` was partial on
`status BETWEEN 200 AND 299` while `host_failures` counted `outcome = 'ok'`; those agreed
only by construction, and a partial index only serves a query whose predicate implies the
index's, so `succeeded` and the index move onto `outcome` together or Postgres silently
stops using it. `ix_page_captures_host_fetched` gains `capture_policy`, which
`host_failures` filters on and was rechecking against every row the index returned.

Two more were written and then measured away. An index on the three decline outcomes is
never chosen — `settled` ORs four branches that between them match four rows in five, and
with `enable_seqscan` off the forced plan was 3.5x slower than the scan. One on
`(parser_version, item_version_id)` is worse: the planner does take it, and the carving
sweep runs 6.4ms against 4.5ms without it, because once the sweep has drained the stamp
matches nearly every row and only the version narrows anything. So the sweep asks per
version and `feed_captures` carries its unique constraint and its two foreign keys.

Revision ID: a0010d3fcfaa
Revises: 5bf73759d4d6
Create Date: 2026-08-20 12:46:53.144443+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a0010d3fcfaa"
down_revision: str | Sequence[str] | None = "5bf73759d4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# No column ever said which feedparser wrote the text, so the carvings moved across here
# cannot claim one. The sweep reads these as due and replaces the stamp.
UNKNOWN_PARSER = "unknown"

FEED_TEXT = "coalesce(nullif(content, ''), summary)"


def _dictionary_scopes() -> None:
    """A discriminator on `zstd_dictionaries`, backfilled from whichever key is set."""
    op.add_column("zstd_dictionaries", sa.Column("scope", sa.String(length=16), nullable=True))
    op.execute(
        "UPDATE zstd_dictionaries "
        "SET scope = CASE WHEN host_id IS NOT NULL THEN 'host_page' ELSE 'feed_document' END"
    )
    op.alter_column("zstd_dictionaries", "scope", nullable=False)

    op.drop_constraint(
        op.f("uq_zstd_dictionaries_dict_id_feed_id_host_id"), "zstd_dictionaries", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_zstd_dictionaries_dict_id_scope_feed_id_host_id"),
        "zstd_dictionaries",
        ["dict_id", "scope", "feed_id", "host_id"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_check_constraint(
        "known_scope",
        "zstd_dictionaries",
        "scope IN ('feed_document', 'feed_item', 'host_page')",
    )
    op.create_check_constraint(
        "scope_matches_key", "zstd_dictionaries", "(scope = 'host_page') = (host_id IS NOT NULL)"
    )


def _feed_captures() -> None:
    op.create_table(
        "feed_captures",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("item_version_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("body_hash", sa.LargeBinary(), nullable=False),
        sa.Column("body", sa.LargeBinary(), server_default=sa.text("''::bytea"), nullable=False),
        sa.Column("dictionary_id", sa.UUID(), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dictionary_id"],
            ["zstd_dictionaries.id"],
            name=op.f("fk_feed_captures_dictionary_id_zstd_dictionaries"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_feed_captures_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_version_id"],
            ["item_versions.id"],
            name=op.f("fk_feed_captures_item_version_id_item_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_captures")),
        sa.UniqueConstraint(
            "item_version_id", "body_hash", name=op.f("uq_feed_captures_item_version_id_body_hash")
        ),
    )
    op.create_index(
        op.f("ix_feed_captures_dictionary_id"), "feed_captures", ["dictionary_id"], unique=False
    )
    op.create_index(
        op.f("ix_feed_captures_document_id"), "feed_captures", ["document_id"], unique=False
    )

    # Hashed on the text, not on what was stored: the constraint answers "is this the
    # same carving", which must not change when a dictionary starts compressing it.
    op.execute(
        f"""
        INSERT INTO feed_captures
                    (item_version_id, document_id, body, body_hash, parser_version, captured_at)
             SELECT id,
                    document_id,
                    convert_to({FEED_TEXT}, 'UTF8'),
                    sha256(convert_to({FEED_TEXT}, 'UTF8')),
                    '{UNKNOWN_PARSER}',
                    observed_at
               FROM item_versions
              WHERE {FEED_TEXT} <> ''
        """
    )


def _feed_extractions() -> None:
    op.create_table(
        "feed_extractions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("feed_capture_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["feed_capture_id"],
            ["feed_captures.id"],
            name=op.f("fk_feed_extractions_feed_capture_id_feed_captures"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["extractions.id"],
            name=op.f("fk_feed_extractions_id_extractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_extractions")),
    )
    op.create_index(
        op.f("ix_feed_extractions_feed_capture_id"),
        "feed_extractions",
        ["feed_capture_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO feed_extractions (id, feed_capture_id)
             SELECT extractions.id, feed_captures.id
               FROM extractions
               JOIN feed_captures
                 ON feed_captures.item_version_id = extractions.item_version_id
              WHERE extractions.source = 'feed'
        """
    )
    # A reading with no artefact to name cannot be stored in the new shape. Derived and
    # rebuildable, which is what the table is for.
    op.execute(
        "DELETE FROM extractions "
        "WHERE source = 'feed' AND id NOT IN (SELECT id FROM feed_extractions)"
    )


def _capture_indexes() -> None:
    op.drop_index("ix_page_captures_succeeded", table_name="page_captures")
    op.create_index(
        "ix_page_captures_succeeded",
        "page_captures",
        ["item_version_id"],
        unique=False,
        postgresql_where=sa.text("outcome = 'ok'"),
    )
    op.drop_index(op.f("ix_page_captures_host_fetched"), table_name="page_captures")
    op.create_index(
        "ix_page_captures_host_fetched",
        "page_captures",
        ["host_id", "capture_policy", sa.literal_column("fetched_at DESC"), "outcome"],
        unique=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    # What a re-parse resolves relative entry links against. `page_captures` has carried
    # this since it existed and for the same reason; the feed side needs it the moment a
    # document is read back rather than read once.
    op.add_column("documents", sa.Column("final_url", sa.Text(), server_default="", nullable=False))
    _dictionary_scopes()
    _feed_captures()
    _feed_extractions()
    op.create_index("ix_item_versions_document_id", "item_versions", ["document_id"], unique=False)
    _capture_indexes()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_page_captures_host_fetched", table_name="page_captures")
    op.create_index(
        op.f("ix_page_captures_host_fetched"),
        "page_captures",
        ["host_id", sa.literal_column("fetched_at DESC"), "outcome"],
        unique=False,
    )
    op.drop_index("ix_page_captures_succeeded", table_name="page_captures")
    op.create_index(
        "ix_page_captures_succeeded",
        "page_captures",
        ["item_version_id"],
        unique=False,
        postgresql_where=sa.text("status BETWEEN 200 AND 299"),
    )

    op.drop_index("ix_item_versions_document_id", table_name="item_versions")
    op.drop_index(op.f("ix_feed_extractions_feed_capture_id"), table_name="feed_extractions")
    op.drop_table("feed_extractions")
    op.drop_index(op.f("ix_feed_captures_document_id"), table_name="feed_captures")
    op.drop_index(op.f("ix_feed_captures_dictionary_id"), table_name="feed_captures")
    op.drop_table("feed_captures")

    # Bare suffixes: the `ck` template interpolates whatever it is handed, so the full
    # name would be dropped as `ck_zstd_dictionaries_ck_zstd_dictionaries_…`.
    op.drop_constraint("scope_matches_key", "zstd_dictionaries", type_="check")
    op.drop_constraint("known_scope", "zstd_dictionaries", type_="check")
    op.drop_constraint(
        op.f("uq_zstd_dictionaries_dict_id_scope_feed_id_host_id"),
        "zstd_dictionaries",
        type_="unique",
    )
    # Item-text dictionaries collide with their feed's document one under the old key.
    op.execute("DELETE FROM zstd_dictionaries WHERE scope = 'feed_item'")
    op.create_unique_constraint(
        op.f("uq_zstd_dictionaries_dict_id_feed_id_host_id"),
        "zstd_dictionaries",
        ["dict_id", "feed_id", "host_id"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_column("zstd_dictionaries", "scope")
    op.drop_column("documents", "final_url")
