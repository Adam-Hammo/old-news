"""drop tables left by the previous orm

Piccolo's admin kept its user and session rows in the database. sqladmin
authenticates against a hash in config instead, so these are dead — but they
still land in every pg_dump, and a restore would then need them.

`migration` is Piccolo's own migration history, replaced by `alembic_version`.

IF EXISTS throughout: a database created after the switch never had them, and
this has to be a no-op there.

Revision ID: fd3da7760685
Revises: 79a05d3214fd
Create Date: 2026-08-14 05:59:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fd3da7760685"
down_revision: str | Sequence[str] | None = "79a05d3214fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ABANDONED = ("sessions", "piccolo_user", "migration")


def upgrade() -> None:
    for table in ABANDONED:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    """Deliberately empty. Recreating an empty table nobody reads is not a rollback."""
