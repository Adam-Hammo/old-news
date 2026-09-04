import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    and_,
    case,
    func,
    select,
    text,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, aliased, column_property, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey
from old_news.db.models.extraction import Extraction, ExtractionSource
from old_news.db.models.feed_capture import FeedCapture
from old_news.db.models.page import PageCapture
from old_news.db.models.subscription import subscribed

if TYPE_CHECKING:
    from old_news.db.models.feed import Feed


# Which reading wins a tie, named rather than left to how the two values happen to sort.
# A source added to the enum and not to this ranks last instead of by its spelling.
READING_PREFERENCE = (ExtractionSource.FEED, ExtractionSource.PAGE)

# Within this much of the longest reading is the same article told twice, not a teaser
# and the article. Two readings of one piece differ by an editor's note, not by half.
FULL_TEXT_SHARE = 0.8

# Below this, length stops being evidence and `structure_count` decides instead.
# Characters rather than paragraphs: plenty of publishers extract as one block.
ARTICLE_CHARS = 500


def _preferred():
    # Compared against the column rather than passed as a `value=` mapping, which binds
    # the sources untyped and leaves asyncpg nothing to send them as.
    return case(
        *((Extraction.source == source, rank) for rank, source in enumerate(READING_PREFERENCE)),
        else_=len(READING_PREFERENCE),
    )


def _ranked(reading: Extraction, fullest: int) -> tuple[bool, bool, int, int, int]:
    """`_fullest_reading`'s ordering for a loaded row. Highest wins, so rank is negated."""
    substantial = reading.char_count >= ARTICLE_CHARS
    ranked = (
        READING_PREFERENCE.index(reading.source)
        if reading.source in READING_PREFERENCE
        else len(READING_PREFERENCE)
    )
    return (
        substantial and reading.char_count >= FULL_TEXT_SHARE * fullest,
        substantial,
        reading.structure_count,
        reading.char_count,
        -ranked,
    )


def _substantial():
    return Extraction.char_count >= ARTICLE_CHARS


def _whole_article():
    """Enough to be an article, and substantially the most of it rather than its teaser."""
    # The window runs over the rows this subquery already filtered to, so "most" is most
    # of what one item holds rather than the longest thing in the archive.
    return and_(
        _substantial(),
        Extraction.char_count >= FULL_TEXT_SHARE * func.max(Extraction.char_count).over(),
    )


def _newest(rows, *, at, among, name: str):
    """This row is the newest `among` its group, with the id breaking a tie in `at`."""
    newer = aliased(rows, name=name)
    return ~(
        select(newer.id)
        .where(among(newer), tuple_(at(newer), newer.id) > tuple_(at(rows), rows.id))
        # `correlate_except`, or the inner half puts the outer row's table in its own FROM
        # and asks whether a newer row exists for *anything*.
        .correlate_except(newer)
        .exists()
    )


def _fullest_reading(scope, correlate):
    """The best of the newest reading per source among `scope`, as a scalar subquery."""
    newest = _newest(
        Extraction,
        at=lambda reading: reading.created_at,
        # Per source, or only the newest reading survives and the fullest never competes.
        among=lambda newer: and_(scope(newer), newer.source == Extraction.source),
        name="newer_reading",
    )
    return func.coalesce(
        select(Extraction.body)
        .where(scope(Extraction), newest)
        .order_by(
            _whole_article().desc(),
            _substantial().desc(),
            Extraction.structure_count.desc(),
            Extraction.char_count.desc(),
            _preferred(),
        )
        .correlate(correlate)
        .limit(1)
        .scalar_subquery(),
        "",
    )


def item_reading(source: ExtractionSource):
    """The newest reading of one source, across every version of an item."""
    versions = select(ItemVersion.id).where(ItemVersion.item_id == Item.id).correlate(Item)
    return func.coalesce(
        select(Extraction.body)
        .where(Extraction.item_version_id.in_(versions), Extraction.source == source)
        .order_by(Extraction.created_at.desc(), Extraction.id.desc())
        .correlate(Item)
        .limit(1)
        .scalar_subquery(),
        "",
    )


def _current_version_join():
    return and_(Item.id == ItemVersion.item_id, ItemVersion.is_head)


def _latest_capture_join():
    """The newest successful capture for a version, if it has one."""
    return and_(
        ItemVersion.id == PageCapture.item_version_id,
        PageCapture.succeeded,
        _newest(
            PageCapture,
            at=lambda capture: capture.fetched_at,
            among=lambda newer: and_(
                newer.item_version_id == PageCapture.item_version_id, newer.succeeded
            ),
            name="newer_capture",
        ),
    )


def _feed_capture_join():
    """The newest text carved out of the feed for a version."""
    return and_(
        ItemVersion.id == FeedCapture.item_version_id,
        _newest(
            FeedCapture,
            at=lambda capture: capture.captured_at,
            among=lambda newer: newer.item_version_id == FeedCapture.item_version_id,
            name="newer_feed_capture",
        ),
    )


def _source_reading_join(source: ExtractionSource):
    """The newest reading of one source for one version."""
    return and_(
        ItemVersion.id == Extraction.item_version_id,
        Extraction.source == source,
        _newest(
            Extraction,
            at=lambda reading: reading.created_at,
            among=lambda newer: and_(
                newer.item_version_id == Extraction.item_version_id, newer.source == source
            ),
            name=f"newer_{source}_reading",
        ),
    )


def _latest_item_extraction_join():
    """The newest extraction of any version of one item — the head may not have one yet."""
    sibling = aliased(ItemVersion, name="sibling_version")
    return and_(
        ItemVersion.id == Extraction.item_version_id,
        _newest(
            Extraction,
            at=lambda reading: reading.created_at,
            among=lambda newer: and_(
                sibling.id == newer.item_version_id, sibling.item_id == ItemVersion.item_id
            ),
            name="newer_item_extraction",
        ),
    )


class Item(UUIDPrimaryKey, Base):
    """An article's identity — nothing a publisher controls."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("feed_id", "identity_key", name="uq_items_feed_identity"),
        Index("ix_items_feed_first_seen", "feed_id", text("first_seen_at DESC"), "id"),
        # What the river pages on. The id is in it because CURRENT_TIMESTAMP is the
        # transaction's, so every item one poll wrote shares a first_seen_at.
        Index("ix_items_river", text("first_seen_at DESC"), text("id DESC")),
    )

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE")
    )
    guid: Mapped[str] = mapped_column(Text, server_default="")
    identity_key: Mapped[str] = mapped_column(Text)
    identity_source: Mapped[str] = mapped_column(String(8), server_default="guid")

    first_seen_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    read_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)

    # Opened is a tap; finished is the bottom of the article. Only the second is
    # evidence of having read it, which is what an issue must not send again.
    finished_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)

    if TYPE_CHECKING:
        # Assigned below the class, since it names `ItemVersion`. Under TYPE_CHECKING the
        # annotation never reaches `__annotations__`, so declarative does not map it.
        version_count: Mapped[int]

    feed: Mapped[Feed] = relationship(lazy="raise")
    versions: Mapped[list[ItemVersion]] = relationship(
        back_populates="item",
        order_by="ItemVersion.id",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    current_version: Mapped[ItemVersion] = relationship(
        primaryjoin=_current_version_join,
        viewonly=True,
        uselist=False,
        lazy="raise",
    )

    current_extraction: Mapped[Extraction | None] = relationship(
        secondary="item_versions",
        primaryjoin=lambda: Item.id == ItemVersion.item_id,
        secondaryjoin=_latest_item_extraction_join,
        viewonly=True,
        uselist=False,
        lazy="raise",
    )

    @hybrid_property
    def subscribed(self) -> bool:
        """Whether we still follow the feed this came from."""
        return self.feed.subscription is not None and self.feed.subscription.active

    @subscribed.inplace.expression
    @classmethod
    def _subscribed_expression(cls):
        return subscribed(cls.feed_id)

    @hybrid_property
    def reading_body(self) -> str:
        """The text to show for this article, across every version of it."""
        raise NotImplementedError("only queryable as SQL; select it rather than loading a row")

    @reading_body.inplace.expression
    @classmethod
    def _reading_body_expression(cls):
        # `correlate` on the inner select too, or `items` lands in its own FROM and the
        # answer is the fullest reading in the archive.
        versions = select(ItemVersion.id).where(ItemVersion.item_id == cls.id).correlate(cls)
        return _fullest_reading(lambda reading: reading.item_version_id.in_(versions), cls)


class ItemVersion(UUIDPrimaryKey, Base):
    """A particular version of an item."""

    __tablename__ = "item_versions"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_item_versions_supersedes"),
        Index(
            "uq_item_versions_head",
            "item_id",
            unique=True,
            postgresql_where=text("supersedes_id IS NULL"),
        ),
        CheckConstraint("supersedes_id IS NULL OR id > supersedes_id", name="key_order"),
        # Postgres doesn't index foreign keys. Ordered by id so it also serves
        # walking an item's chain and finding its tail.
        Index("ix_item_versions_item_id", "item_id", "id"),
        # Half of what search reads; the other half is on `extractions`. Declared here so
        # autogenerate knows it exists — undeclared, the next revision drops it.
        Index(
            "ix_item_versions_title_bm25",
            "id",
            "title",
            postgresql_using="bm25",
            postgresql_with={"key_field": "id"},
        ),
        # What the feed capture sweep groups by, and what a document delete has to find.
        Index("ix_item_versions_document_id", "document_id"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE"), nullable=True
    )
    observed_at: Mapped[datetime.datetime] = mapped_column(
        Timestamptz, server_default=NOW, index=True
    )

    title: Mapped[str] = mapped_column(Text, server_default="")
    author: Mapped[str] = mapped_column(Text, server_default="")
    url: Mapped[str] = mapped_column(Text, server_default="")
    canonical_url: Mapped[str] = mapped_column(Text, server_default="", index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    enclosures: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    comments_url: Mapped[str] = mapped_column(Text, server_default="")
    published_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)
    updated_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)

    content_hash: Mapped[bytes] = mapped_column(LargeBinary)

    item: Mapped[Item] = relationship(back_populates="versions", lazy="raise")
    supersedes: Mapped[ItemVersion | None] = relationship(
        remote_side=lambda: [ItemVersion.id],
        back_populates="superseded_by",
        lazy="raise",
    )
    # One-to-one by `uq_item_versions_supersedes`. Its absence is what "head" means, which
    # is what lets `is_head` answer in Python as well as in SQL.
    superseded_by: Mapped[ItemVersion | None] = relationship(
        back_populates="supersedes", uselist=False, lazy="raise"
    )

    @hybrid_property
    def is_head(self) -> bool:
        """The version nothing supersedes — not `supersedes_id IS NULL`, the chain's other end."""
        return self.superseded_by is None

    @is_head.inplace.expression
    @classmethod
    def _is_head_expression(cls):
        successor = aliased(cls, name="successor")
        return ~select(successor.id).where(successor.supersedes_id == cls.id).exists()

    # The artefacts behind one version, and the newest reading of each. Every foreign
    # key cascades in Postgres, so none of these needs an ORM cascade to clean up.
    latest_capture: Mapped[PageCapture | None] = relationship(
        primaryjoin=_latest_capture_join, viewonly=True, uselist=False, lazy="raise"
    )
    feed_capture: Mapped[FeedCapture | None] = relationship(
        primaryjoin=_feed_capture_join, viewonly=True, uselist=False, lazy="raise"
    )
    feed_extraction: Mapped[Extraction | None] = relationship(
        primaryjoin=lambda: _source_reading_join(ExtractionSource.FEED),
        viewonly=True,
        uselist=False,
        lazy="raise",
    )
    page_extraction: Mapped[Extraction | None] = relationship(
        primaryjoin=lambda: _source_reading_join(ExtractionSource.PAGE),
        viewonly=True,
        uselist=False,
        lazy="raise",
    )

    @hybrid_property
    def has_feed_text(self) -> bool:
        """Whether the capture a feed reading would read has anything in it."""
        return bool(self.feed_capture and self.feed_capture.body)

    @has_feed_text.inplace.expression
    @classmethod
    def _has_feed_text_expression(cls):
        # The newest, not any: that is the one `pending_feed` expands, so a sweep asking
        # anything wider would hand it a version it returns nothing for.
        newest = (
            select(func.octet_length(FeedCapture.body))
            .where(FeedCapture.item_version_id == cls.id)
            .order_by(FeedCapture.captured_at.desc(), FeedCapture.id.desc())
            .correlate(cls)
            .limit(1)
            .scalar_subquery()
        )
        return func.coalesce(newest, 0) > 0

    @hybrid_property
    def reading_body(self) -> str:
        """The text a reader should be shown: whichever reading of this version reads best."""
        readings = [read for read in (self.feed_extraction, self.page_extraction) if read]
        if not readings:
            return ""
        fullest = max(read.char_count for read in readings)
        return max(readings, key=lambda read: _ranked(read, fullest)).body

    @reading_body.inplace.expression
    @classmethod
    def _reading_body_expression(cls):
        return _fullest_reading(lambda reading: reading.item_version_id == cls.id, cls)

    def __str__(self) -> str:
        return self.title or self.url


# Out of the class body because it names `ItemVersion`. Deferred, so a correlated
# count is not a tax on every `select(Item)`.
Item.version_count = column_property(
    select(func.count(ItemVersion.id))
    .where(ItemVersion.item_id == Item.id)
    .correlate_except(ItemVersion)
    .scalar_subquery(),
    deferred=True,
)
