import datetime
import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey

# Named explicitly: the convention's template runs past Postgres' 63-char limit.
RENDITION_KEY = "uq_image_renditions_capture_spec_encoder"
RENDITION_IDENTITY = ("image_capture_id", "spec", "encoder_version")


class ImageRendition(UUIDPrimaryKey, Base):
    """An image re-encoded for reading. Derived, disposable, rebuildable from the capture."""

    __tablename__ = "image_renditions"
    __table_args__ = (UniqueConstraint(*RENDITION_IDENTITY, name=RENDITION_KEY),)

    image_capture_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("image_captures.id", ondelete="CASCADE")
    )

    # The recipe asked for, and what carried it out. Bumping either makes the archive due
    # again, the same bargain `extractor_version` and `parser_version` make.
    spec: Mapped[str] = mapped_column(String(16))
    encoder_version: Mapped[str] = mapped_column(String(32))

    content_type: Mapped[str] = mapped_column(String(64), server_default="")
    width: Mapped[int] = mapped_column(Integer, server_default="0")
    height: Mapped[int] = mapped_column(Integer, server_default="0")

    # Empty when nothing beat the bytes as served, which is an answer and not a failure:
    # it says read the capture, and it stops the sweep offering this one forever.
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    byte_size: Mapped[int] = mapped_column(Integer, server_default="0")

    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    def __str__(self) -> str:
        return f"{self.spec}: {self.byte_size} bytes"
