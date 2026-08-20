import datetime
import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class ImageCapture(UUIDPrimaryKey, Base):
    """One image, as served. Keyed on URL and bytes together, and never re-encoded."""

    __tablename__ = "image_captures"
    __table_args__ = (UniqueConstraint("url_digest", "body_hash"),)

    url: Mapped[str] = mapped_column(Text)
    # Keyed instead of `url`: an image URL can exceed what btree takes, and a CDN's query
    # string is part of its identity. No separate index — it leads the constraint above.
    url_digest: Mapped[bytes] = mapped_column(LargeBinary)

    host_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id"), index=True
    )

    # Where it actually came from. A hop to another host is checked against that host's
    # rules before anything is kept, so this is the record of what was asked.
    final_url: Mapped[str] = mapped_column(Text, server_default="")

    fetched_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
    status: Mapped[int] = mapped_column(Integer, server_default="0")

    content_type: Mapped[str] = mapped_column(String(64), server_default="")
    body_hash: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    byte_size: Mapped[int] = mapped_column(Integer, server_default="0")

    error: Mapped[str] = mapped_column(Text, server_default="")
