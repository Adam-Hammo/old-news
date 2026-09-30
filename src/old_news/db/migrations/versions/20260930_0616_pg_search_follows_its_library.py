"""pg_search follows its library

A new image swaps `pg_search.so`, but an extension's SQL objects are only created by
`create extension` — which initdb runs on a fresh volume and never again. An existing
database keeps the catalog of whichever version first created it, running against a newer
library, until something says `alter extension ... update`. Tests never see this: every
test database is fresh, so it is created at the new version already.

Pinned rather than a bare `update`, so a revision run against an image that does not yet
carry the version fails instead of quietly updating to whatever is there.
`tests/unit/test_deployment.py` holds the pin to the image tag, so a bump without its
revision fails in the diff that makes it.

The downgrade is a no-op: pg_search ships upgrade scripts and no downgrade ones, and the
older library would be running against this catalog either way.

Revision ID: 10f563a4931f
Revises: c3d9f021b796

"""

from collections.abc import Sequence

from alembic import op

revision: str = "10f563a4931f"
down_revision: str | Sequence[str] | None = "c3d9f021b796"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter extension pg_search update to '0.25.10'")


def downgrade() -> None:
    """Downgrade schema."""
