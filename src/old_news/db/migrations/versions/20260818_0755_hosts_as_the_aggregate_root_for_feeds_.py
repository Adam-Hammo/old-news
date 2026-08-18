"""hosts as the aggregate root for feeds and robots

A publisher is an entity, not a value derived from a feed URL — it owns robots rules
and a crawl delay, and later whatever else gets observed about it. So `feeds` and
`robots_policies` both reference it, and nothing references them back: the policy
cache stays droppable.

The backfill derives each host with a frozen copy of `politeness.host_of` rather than
importing it, so this keeps producing the same result whatever that function becomes.
It refuses to run rather than guess if a feed has no derivable host; `feeds.host_id`
is not nullable, and a feed with no host was never pollable.

Revision ID: f08d0d17d77f
Revises: fbddd5978dfe
Create Date: 2026-08-18 07:55:36.283366+00:00

"""

from collections.abc import Sequence
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f08d0d17d77f"
down_revision: str | Sequence[str] | None = "fbddd5978dfe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _host_of(url: str) -> str:
    """Frozen copy of politeness.host_of. Do not import the real one."""
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in {"http", "https"}:
        return ""
    try:
        host = (parts.hostname or "").encode("idna").decode("ascii")
    except UnicodeError, ValueError:
        host = parts.hostname or ""
    return host.removeprefix("www.")


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hosts")),
    )
    op.create_index(op.f("ix_hosts_name"), "hosts", ["name"], unique=True)

    op.add_column("feeds", sa.Column("host_id", sa.Uuid(), nullable=True))
    op.add_column("robots_policies", sa.Column("host_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    feeds = [
        (row[0], _host_of(row[1])) for row in bind.execute(sa.text("SELECT id, url FROM feeds"))
    ]

    unpollable = [str(feed_id) for feed_id, host in feeds if not host]
    if unpollable:
        raise RuntimeError(
            f"{len(unpollable)} feeds have no pollable host, so feeds.host_id cannot be "
            "set: DELETE them first (they have never been fetchable), then re-run. "
            f"ids: {', '.join(unpollable)}"
        )

    names = {host for _, host in feeds}
    names |= set(bind.scalars(sa.text("SELECT host FROM robots_policies")))
    names.discard("")
    if names:
        bind.execute(
            sa.text("INSERT INTO hosts (name) SELECT unnest(CAST(:names AS text[]))"),
            {"names": sorted(names)},
        )

    for feed_id, host in feeds:
        bind.execute(
            sa.text(
                "UPDATE feeds SET host_id = (SELECT id FROM hosts WHERE name = :host) "
                "WHERE id = :id"
            ),
            {"host": host, "id": feed_id},
        )
    bind.execute(
        sa.text("UPDATE robots_policies r SET host_id = h.id FROM hosts h WHERE h.name = r.host")
    )

    op.alter_column("feeds", "host_id", nullable=False)
    op.alter_column("robots_policies", "host_id", nullable=False)

    op.create_index(op.f("ix_feeds_host_id"), "feeds", ["host_id"], unique=False)
    op.create_foreign_key(op.f("fk_feeds_host_id_hosts"), "feeds", "hosts", ["host_id"], ["id"])
    op.create_index(op.f("ix_robots_policies_host_id"), "robots_policies", ["host_id"], unique=True)
    op.create_foreign_key(
        op.f("fk_robots_policies_host_id_hosts"), "robots_policies", "hosts", ["host_id"], ["id"]
    )
    op.drop_index(op.f("ix_robots_policies_host"), table_name="robots_policies")
    op.drop_column("robots_policies", "host")


def downgrade() -> None:
    op.add_column("robots_policies", sa.Column("host", sa.Text(), nullable=True))
    op.execute("UPDATE robots_policies r SET host = h.name FROM hosts h WHERE h.id = r.host_id")
    op.alter_column("robots_policies", "host", nullable=False)
    op.create_index(op.f("ix_robots_policies_host"), "robots_policies", ["host"], unique=True)

    op.drop_constraint(
        op.f("fk_robots_policies_host_id_hosts"), "robots_policies", type_="foreignkey"
    )
    op.drop_index(op.f("ix_robots_policies_host_id"), table_name="robots_policies")
    op.drop_column("robots_policies", "host_id")

    op.drop_constraint(op.f("fk_feeds_host_id_hosts"), "feeds", type_="foreignkey")
    op.drop_index(op.f("ix_feeds_host_id"), table_name="feeds")
    op.drop_column("feeds", "host_id")

    op.drop_index(op.f("ix_hosts_name"), table_name="hosts")
    op.drop_table("hosts")
