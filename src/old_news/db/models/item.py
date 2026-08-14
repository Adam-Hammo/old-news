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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, aliased, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey

if TYPE_CHECKING:
    from old_news.db.models.feed import Feed

IDENTITY_SOURCES = ("guid", "link", "hash")


def _current_version_join():
    successor = aliased(ItemVersion, name="successor")
    return and_(
        Item.id == ItemVersion.item_id,
        ~select(successor.id).where(successor.supersedes_id == ItemVersion.id).exists(),
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
        remote_side=lambda: [ItemVersion.id], lazy="raise"
    )

    def __str__(self) -> str:
        return self.title or self.url
