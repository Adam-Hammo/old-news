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


# What makes a reading the same reading. The upsert in `extract/service.py` matches on
# this constraint and must not rewrite the columns it matched, so both are declared here
# and the constraint is built from the tuple.
READING_KEY = "uq_extractions_version_source_extractor"
READING_IDENTITY = ("item_version_id", "source", "extractor", "extractor_version")


class ExtractionSource(enum.StrEnum):
    """Which stored artefact was read."""

    FEED = "feed"
    PAGE = "page"


class Extraction(UUIDPrimaryKey, Base):
    """What one extractor made of one artefact. Derived, disposable, rebuildable.

    Abstract in practice: no identity of its own, and `source` is NOT NULL with no
    default, so the database refuses a row that will not say which kind it is.
    """

    __tablename__ = "extractions"
    __table_args__ = (
        # Also serves lookups by version, which leads it. Named explicitly because the
        # convention's template runs to 65 characters and Postgres truncates at 63.
        UniqueConstraint(*READING_IDENTITY, name=READING_KEY),
        # What the extraction sweep asks: which versions has this extractor not done. The
        # unique constraint cannot serve it, because the extractor is not its leading
        # column.
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

    # Captured, not yet materialised: turning these into article-to-article rows needs
    # URL-to-item resolution, which arrives with dedup in the search phase.
    links: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    # Measurements, not judgements: pure functions of `body`, so they cannot go stale.
    # Whether they are good enough is a threshold question, and thresholds live in config.
    char_count: Mapped[int] = mapped_column(Integer, server_default="0")
    paragraph_count: Mapped[int] = mapped_column(Integer, server_default="0")
    link_density: Mapped[float] = mapped_column(Float, server_default="0")

    # RUF012 wants ClassVar; SQLAlchemy declares it as an instance attribute and `ty`
    # rejects the override. Plain assignment is what SQLAlchemy's own docs use.
    __mapper_args__ = {"polymorphic_on": source}  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.source}: {self.char_count} characters"


class FeedExtraction(Extraction):
    """A reading of the text a feed already carried.

    Adds nothing on purpose, so neither source is the default one. No `__tablename__`,
    so no second table and no join — just a name for the identity.
    """

    __mapper_args__ = {"polymorphic_identity": ExtractionSource.FEED}  # noqa: RUF012


class PageExtraction(Extraction):
    """A reading of an article page, plus what that page claimed about itself.

    Claims stay claims rather than being merged over what the feed said — which to
    believe is a question for a reader. A feed states its own on the version instead.
    """

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

    # Eager, or the child columns lazy-load and fail once a row outlives its transaction.
    # Not `"inline"`: that outer-joins this table into the aliased subquery
    # `Item.current_extraction` builds, which has no FROM clause to attach it to.
    __mapper_args__ = {  # noqa: RUF012
        "polymorphic_identity": ExtractionSource.PAGE,
        "polymorphic_load": "selectin",
    }

    def __str__(self) -> str:
        return self.title or f"page: {self.char_count} characters"


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
