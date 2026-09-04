"""a search index over titles and readings

Two BM25 indexes rather than one, because the text is in two tables: a headline lives on
`item_versions` and the article on `extractions`. A single index would need both columns
side by side, which means a third table copying what the first two already say — and a
copy of the archive that a task has to keep in step is a copy that will drift. Real
indexes on the real columns are maintained by Postgres on every write instead, so search
is never stale and nothing has to be rebuilt after a backfill.

The cost is that scores from the two are not strictly comparable, so nothing tries: a
title match outranks a body match, and BM25 only breaks the tie within each. That is
`ui/search.py`'s job and it is the whole ranking.

`pg_search` needs `shared_preload_libraries`, which `compose.yaml` sets, and it depends on
`vector` — created here for that reason alone. Embeddings are a later question and this
revision does not begin answering it.

The indexes cover every version and every reading. Restricting them to the head version
would need a predicate the access method does not take, so `is_head` is a condition in the
query, where the roadmap says search belongs: the reading version, not the history.

Revision ID: 49e46b633183
Revises: 251a8cbf84f6

"""

from collections.abc import Sequence

from alembic import op

revision: str = "49e46b633183"
down_revision: str | Sequence[str] | None = "251a8cbf84f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TITLES = "ix_item_versions_title_bm25"
BODIES = "ix_extractions_body_bm25"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("create extension if not exists vector")
    op.execute("create extension if not exists pg_search")
    op.execute(
        f"create index {TITLES} on item_versions using bm25 (id, title) with (key_field='id')"
    )
    op.execute(f"create index {BODIES} on extractions using bm25 (id, body) with (key_field='id')")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"drop index if exists {BODIES}")
    op.execute(f"drop index if exists {TITLES}")
    op.execute("drop extension if exists pg_search")
