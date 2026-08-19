import datetime
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of


class ImageRole(enum.StrEnum):
    """What an image is to its article."""

    # The one the page puts forward as representing itself, and the only one fetched
    # without being asked for.
    LEAD = "lead"
    BODY = "body"


class Extraction(UUIDPrimaryKey, Base):
    """What one extractor made of one captured page.

    Derived and disposable, versioned on two axes — which item version it came from and
    which extractor made it. Re-extracting with the same extractor is idempotent; a new
    extractor version inserts alongside, and old output can be binned freely because the
    page it came from is still there.
    """

    __tablename__ = "extractions"
    __table_args__ = (
        # Also the index for looking one up by version: `item_version_id` leads it, so a
        # separate single-column index on that would be a second copy of the same b-tree.
        UniqueConstraint("item_version_id", "extractor", "extractor_version"),
        # What the extraction sweep asks: which versions has this extractor not done. The
        # unique constraint cannot serve it, because the extractor is not its leading
        # column.
        Index("ix_extractions_extractor", "extractor", "extractor_version"),
    )

    item_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE")
    )
    page_capture_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("page_captures.id", ondelete="CASCADE"), index=True
    )

    extractor: Mapped[str] = mapped_column(String(32))
    extractor_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    body: Mapped[str] = mapped_column(Text, server_default="")

    # What the page claims about itself, kept as claims rather than merged over what the
    # feed said. Which of the two to believe is a question for a reader, later.
    title: Mapped[str] = mapped_column(Text, server_default="")
    byline: Mapped[str] = mapped_column(Text, server_default="")
    language: Mapped[str] = mapped_column(String(32), server_default="")
    site_name: Mapped[str] = mapped_column(Text, server_default="")
    page_type: Mapped[str] = mapped_column(String(32), server_default="")
    published_claim: Mapped[str] = mapped_column(String(32), server_default="")

    # Captured, not yet materialised: turning these into article-to-article rows needs
    # URL-to-item resolution, which arrives with dedup in the search phase.
    links: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    # The quality signal. The failure that matters is not a 404, it is cheerfully
    # extracting a cookie banner and marking it done.
    char_count: Mapped[int] = mapped_column(Integer, server_default="0")
    paragraph_count: Mapped[int] = mapped_column(Integer, server_default="0")
    link_density: Mapped[float] = mapped_column(Float, server_default="0")
    feed_body_ratio: Mapped[float] = mapped_column(Float, server_default="0")

    ok: Mapped[bool] = mapped_column(server_default=text("false"))
    note: Mapped[str] = mapped_column(Text, server_default="")

    def __str__(self) -> str:
        return self.title or f"{self.char_count} characters"


class ExtractionImage(UUIDPrimaryKey, Base):
    """One image an extraction found, and the capture that satisfied it if any.

    A row rather than JSONB because it points at `image_captures`, and because rendering
    an article with its pictures should be one join.
    """

    __tablename__ = "extraction_images"
    __table_args__ = (
        CheckConstraint(one_of("role", ImageRole), name="known_role"),
        # Leading column serves lookups by extraction, so no separate index for it.
        UniqueConstraint("extraction_id", "url"),
        # What the image sweep asks, and only ever about slots with nothing fetched — so
        # partial, which keeps it small as the archive fills up.
        Index(
            "ix_extraction_images_wanted",
            "role",
            postgresql_where=text("image_capture_id IS NULL"),
        ),
    )

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extractions.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(Text)
    # Null until something fetches it. A lead image is fetched unasked; the rest wait for
    # a reader, a Kindle build or a label to ask.
    image_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("image_captures.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(8))
    alt: Mapped[str] = mapped_column(Text, server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default="0")

    def __str__(self) -> str:
        return f"{self.role}: {self.url}"
