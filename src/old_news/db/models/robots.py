import datetime
import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class RobotsPolicy(UUIDPrimaryKey, Base):
    """One host's robots.txt, refreshed on a timer.

    A cache, not archive: overwritten in place and rebuildable from the network, so
    the append-only rules don't apply. It points at `hosts` and nothing points back,
    so it can be dropped and rebuilt whenever the parsing changes.
    """

    __tablename__ = "robots_policies"

    host_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id"), unique=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, server_default="")

    # 0 when unreachable. Both allow, but a 5xx is worth telling from a 404.
    status: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str] = mapped_column(Text, server_default="")

    crawl_delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    fetched_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
    # Not indexed: the sweep looks up by host and compares this in Python.
    expires_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
