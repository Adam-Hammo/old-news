import datetime
import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class ImageCapture(UUIDPrimaryKey, Base):
    """The one image held for a URL, re-encoded for reading. Content-addressed on service."""

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

    # Of the bytes as served, which `body` stops being once re-encoded. It stays the
    # fingerprint of what the publisher sent, so the same image behind two feeds is still
    # one row and one fetch.
    body_hash: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    byte_size: Mapped[int] = mapped_column(Integer, server_default="0")

    # What `body` was re-encoded to, and what did it. Empty means as served and not yet
    # read: the sweep asks for anything the current encoder has not touched, so bumping
    # either brings the archive back around.
    spec: Mapped[str] = mapped_column(String(16), server_default="")
    encoder_version: Mapped[str] = mapped_column(String(32), server_default="")

    error: Mapped[str] = mapped_column(Text, server_default="")

    @hybrid_property
    def usable(self) -> bool:
        """Bytes a slot may point at: an answer, and actually an image."""
        return (
            bool(self.body) and 200 <= self.status < 300 and self.content_type.startswith("image/")
        )

    @usable.inplace.expression
    @classmethod
    def _usable_expression(cls):
        return (
            (cls.body != b"") & cls.status.between(200, 299) & cls.content_type.startswith("image/")
        )
