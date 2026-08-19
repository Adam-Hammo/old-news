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
from old_news.db.models.extraction import Extraction
from old_news.db.models.page import PageCapture
from old_news.db.models.subscription import subscribed

if TYPE_CHECKING:
    from old_news.db.models.feed import Feed


def _fuller(extracted, feed):
    """Whichever of the two texts is longer, as SQL. Null extraction counts as empty."""
    return case(
        (
            func.length(func.coalesce(extracted, "")) > func.length(feed),
            func.coalesce(extracted, ""),
        ),
        else_=feed,
    )


def _current_version_join():
    return and_(Item.id == ItemVersion.item_id, ItemVersion.is_head)


def _latest_capture_join():
    """The newest successful capture for a version, if it has one."""
    newer = aliased(PageCapture, name="newer_capture")
    return and_(
        ItemVersion.id == PageCapture.item_version_id,
        PageCapture.succeeded,
        ~select(newer.id)
        .where(
            newer.item_version_id == PageCapture.item_version_id,
            newer.succeeded,
            # The id breaks a tie, so "latest" is one row rather than sometimes two.
            tuple_(newer.fetched_at, newer.id) > tuple_(PageCapture.fetched_at, PageCapture.id),
        )
        .exists(),
    )


def _latest_extraction_join():
    """The newest extraction of one version.

    Newest rather than "from the current extractor", which would mean this layer importing
    `extract/` to learn a version string. Bumping the extractor inserts a row, so the
    newest is the current one either way.
    """
    newer = aliased(Extraction, name="newer_extraction")
    return and_(
        ItemVersion.id == Extraction.item_version_id,
        ~select(newer.id)
        .where(
            newer.item_version_id == Extraction.item_version_id,
            tuple_(newer.created_at, newer.id) > tuple_(Extraction.created_at, Extraction.id),
        )
        .exists(),
    )


def _latest_item_extraction_join():
    """The newest extraction of any version of one item.

    Deliberately not the head version's extraction. An edit makes a new version the head,
    and its page waits out the settle window before it is fetched and read — so scoping
    this to the head would blank an article for an hour every time a publisher touched it,
    with a perfectly good extraction of the previous version sitting right there.
    """
    newer = aliased(Extraction, name="newer_item_extraction")
    sibling = aliased(ItemVersion, name="sibling_version")
    return and_(
        ItemVersion.id == Extraction.item_version_id,
        ~select(newer.id)
        .join(sibling, sibling.id == newer.item_version_id)
        .where(
            sibling.item_id == ItemVersion.item_id,
            tuple_(newer.created_at, newer.id) > tuple_(Extraction.created_at, Extraction.id),
        )
        .exists(),
    )


class Item(UUIDPrimaryKey, Base):
    """An article's identity — nothing a publisher controls."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("feed_id", "identity_key", name="uq_items_feed_identity"),
        Index("ix_items_feed_first_seen", "feed_id", text("first_seen_at DESC"), "id"),
    )

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE")
    )
    guid: Mapped[str] = mapped_column(Text, server_default="")
    identity_key: Mapped[str] = mapped_column(Text)
    identity_source: Mapped[str] = mapped_column(String(8), server_default="guid")

    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        Timestamptz, server_default=NOW, index=True
    )

    read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    read_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)

    if TYPE_CHECKING:
        # Assigned below the class, because it names `ItemVersion`. Declared here so a
        # type checker knows it exists; the annotation never reaches `__annotations__`,
        # so declarative does not try to map it as a column.
        version_count: Mapped[int]

    feed: Mapped[Feed] = relationship(lazy="raise")
    versions: Mapped[list[ItemVersion]] = relationship(
        back_populates="item",
        order_by="ItemVersion.id",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    # The tail of the chain: the version nothing supersedes. lazy="raise" guards
    # against a per-row lazy load, not against the join, which is cheap.
    current_version: Mapped[ItemVersion] = relationship(
        primaryjoin=_current_version_join,
        viewonly=True,
        uselist=False,
        lazy="raise",
    )

    # The best text we hold for this article, from whichever version was last read.
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
        """Whether we still follow the feed this came from.

        Every sweep needs it, and this is cheaper to read than a join to `subscriptions`
        for one boolean.
        """
        return self.feed.subscription is not None and self.feed.subscription.active

    @subscribed.inplace.expression
    @classmethod
    def _subscribed_expression(cls):
        return subscribed(cls.feed_id)

    @hybrid_property
    def reading_body(self) -> str:
        """The text to show for this article: whichever of the two is fuller."""
        extracted = self.current_extraction.body if self.current_extraction else ""
        feed = self.current_version.feed_body if self.current_version else ""
        return extracted if len(extracted) > len(feed) else feed

    @reading_body.inplace.expression
    @classmethod
    def _reading_body_expression(cls):
        feed = (
            select(ItemVersion.feed_body)
            .where(_current_version_join())
            .correlate(cls)
            .limit(1)
            .scalar_subquery()
        )
        # Ordered rather than anti-joined: a scalar subquery may sort and limit, which a
        # relationship's primaryjoin may not.
        extracted = (
            select(Extraction.body)
            .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
            .where(ItemVersion.item_id == cls.id)
            .order_by(Extraction.created_at.desc(), Extraction.id.desc())
            .correlate(cls)
            .limit(1)
            .scalar_subquery()
        )
        return _fuller(extracted, feed)


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
    summary: Mapped[str] = mapped_column(Text, server_default="")
    content: Mapped[str] = mapped_column(Text, server_default="")
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
        """The tail of the chain: the version nothing supersedes.

        The most-repeated predicate in the codebase, and the easiest to get subtly wrong —
        note that it is *not* `supersedes_id IS NULL`, which is the chain's other end.
        """
        return self.superseded_by is None

    @is_head.inplace.expression
    @classmethod
    def _is_head_expression(cls):
        successor = aliased(cls, name="successor")
        return ~select(successor.id).where(successor.supersedes_id == cls.id).exists()

    @hybrid_property
    def feed_body(self) -> str:
        """What the feed itself gave us for this version."""
        return self.content or self.summary

    @feed_body.inplace.expression
    @classmethod
    def _feed_body_expression(cls):
        return func.coalesce(func.nullif(cls.content, ""), cls.summary)

    # The newest capture that answered, and the newest text read out of one. Both
    # foreign keys cascade in Postgres, so neither needs an ORM cascade to clean up.
    latest_capture: Mapped[PageCapture | None] = relationship(
        primaryjoin=_latest_capture_join, viewonly=True, uselist=False, lazy="raise"
    )
    latest_extraction: Mapped[Extraction | None] = relationship(
        primaryjoin=_latest_extraction_join, viewonly=True, uselist=False, lazy="raise"
    )

    @hybrid_property
    def reading_body(self) -> str:
        """The text a reader should be shown: whichever of the two is fuller."""
        extracted = self.latest_extraction.body if self.latest_extraction else ""
        return extracted if len(extracted) > len(self.feed_body) else self.feed_body

    @reading_body.inplace.expression
    @classmethod
    def _reading_body_expression(cls):
        extracted = (
            select(Extraction.body)
            .where(Extraction.item_version_id == cls.id)
            .order_by(Extraction.created_at.desc(), Extraction.id.desc())
            .correlate(cls)
            .limit(1)
            .scalar_subquery()
        )
        return _fuller(extracted, cls.feed_body)

    def __str__(self) -> str:
        return self.title or self.url


# Out of the class body because it names `ItemVersion`, which does not exist yet while
# `Item` is being defined. Deferred, so a correlated count is not a tax on every
# `select(Item)` — the capture sweep asks for it in a WHERE, and the list views never do.
Item.version_count = column_property(
    select(func.count(ItemVersion.id))
    .where(ItemVersion.item_id == Item.id)
    .correlate_except(ItemVersion)
    .scalar_subquery(),
    deferred=True,
)
