"""the image owns its extensions

`initdb/10-extensions.sql` was a second owner, and an unreliable one: it runs once per
volume, so a volume older than one of its lines never gets that extension. `vectorscale`
is missing from at least one database for exactly that reason. Revisions now create every
extension the image ships, and pin each to the version the image carries, so the catalog
follows the library through every bump the same way `pg_search` already does.

`vector` also moved off apt, whose package floats with every rebuild, onto the pgvector
image, whose tag is a version.

The downgrade is a no-op, for the same reason as the revision before it.

Revision ID: 8cd702379b3d
Revises: 10f563a4931f

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8cd702379b3d"
down_revision: str | Sequence[str] | None = "10f563a4931f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("create extension if not exists vector")
    op.execute("alter extension vector update to '0.8.6'")
    op.execute("create extension if not exists vectorscale")
    op.execute("alter extension vectorscale update to '0.9.0'")


def downgrade() -> None:
    """Downgrade schema."""
