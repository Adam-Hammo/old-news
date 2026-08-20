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

    LEAD = "lead"
    BODY = "body"


# The upsert matches on this constraint and must not rewrite the columns it matched, so
# the constraint is built from the tuple rather than repeating it.
READING_KEY = "uq_extractions_version_source_extractor"
READING_IDENTITY = ("item_version_id", "source", "extractor", "extractor_version")


class ExtractionSource(enum.StrEnum):
    """Which stored artefact was read."""

    FEED = "feed"
    PAGE = "page"


class Extraction(UUIDPrimaryKey, Base):
    """What one extractor made of one artefact. Derived, disposable, rebuildable."""

    __tablename__ = "extractions"
    __table_args__ = (
        # Named explicitly: the convention's template exceeds Postgres' 63-char limit.
        UniqueConstraint(*READING_IDENTITY, name=READING_KEY),
        # The extractor does not lead the unique constraint, so it cannot serve the sweep.
        Index("ix_extractions_extractor", "extractor", "extractor_version"),
        CheckConstraint(one_of("source", ExtractionSource), name="known_source"),
    )

    item_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(8))

    extractor: Mapped[str] = mapped_column(String(32))
    extractor_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    body: Mapped[str] = mapped_column(Text, server_default="")

    links: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    # Measurements, not judgements. The thresholds live in config.
    char_count: Mapped[int] = mapped_column(Integer, server_default="0")
    paragraph_count: Mapped[int] = mapped_column(Integer, server_default="0")
    link_density: Mapped[float] = mapped_column(Float, server_default="0")

    # RUF012 wants ClassVar, which `ty` then rejects against SQLAlchemy's declaration.
    __mapper_args__ = {"polymorphic_on": source}  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.source}: {self.char_count} characters"


class FeedExtraction(Extraction):
    """A reading of the text a feed already carried. No table of its own, just an identity."""

    __mapper_args__ = {"polymorphic_identity": ExtractionSource.FEED}  # noqa: RUF012


class PageExtraction(Extraction):
    """A reading of an article page, plus what that page claimed about itself."""

    __tablename__ = "page_extractions"

    # Not `UUIDPrimaryKey`: the child shares the parent's key rather than minting one.
    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extractions.id", ondelete="CASCADE"), primary_key=True
    )
    page_capture_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("page_captures.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(Text, server_default="")
    byline: Mapped[str] = mapped_column(Text, server_default="")
    language: Mapped[str] = mapped_column(String(32), server_default="")
    site_name: Mapped[str] = mapped_column(Text, server_default="")
    page_type: Mapped[str] = mapped_column(String(32), server_default="")
    published_claim: Mapped[str] = mapped_column(String(32), server_default="")

    # Eager, or child columns lazy-load and fail once a row outlives its transaction.
    # Not `"inline"`: `Item.current_extraction` builds an aliased subquery with no FROM
    # for it to attach to.
    __mapper_args__ = {  # noqa: RUF012
        "polymorphic_identity": ExtractionSource.PAGE,
        "polymorphic_load": "selectin",
    }

    def __str__(self) -> str:
        return self.title or f"page: {self.char_count} characters"


class ExtractionImage(UUIDPrimaryKey, Base):
    """One image an extraction found, and the capture that satisfied it if any."""

    __tablename__ = "extraction_images"
    __table_args__ = (
        CheckConstraint(one_of("role", ImageRole), name="known_role"),
        UniqueConstraint("extraction_id", "url"),
        # Partial: the sweep only ever asks about slots with nothing fetched.
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
    image_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("image_captures.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(8))
    alt: Mapped[str] = mapped_column(Text, server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default="0")

    def __str__(self) -> str:
        return f"{self.role}: {self.url}"
