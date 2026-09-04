import datetime
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    Interval,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of


class Tier(enum.StrEnum):
    """How much trouble a feed is worth. Each level takes everything the one below does."""

    # Skimmed and gone: a lead image, a short window, never a book.
    WIRE = "wire"
    # Kept properly, so every picture is worth holding.
    ARCHIVE = "archive"
    # Kept, and read as a book.
    KINDLE = "kindle"


# Ascending, named rather than left to how the values happen to sort — 'wire' outranks
# 'archive' alphabetically, which is the opposite of what it means. A tier added to the
# enum and not to this is not comparable at all, which fails loudly.
TIERS = (Tier.WIRE, Tier.ARCHIVE, Tier.KINDLE)

if TYPE_CHECKING:
    from old_news.db.models.feed import Feed


class Subscription(UUIDPrimaryKey, Base):
    """Following a feed, as distinct from the feed itself. `active` is a choice, not a fault."""

    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint(one_of("tier", Tier), name="known_tier"),)

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), unique=True
    )
    category: Mapped[str] = mapped_column(Text, server_default="", index=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), index=True)
    added_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    # An interval rather than seconds, so the cutoff is `now() - expires_after` and
    # Postgres does the arithmetic. Null is a feed nothing ages out of.
    expires_after: Mapped[datetime.timedelta | None] = mapped_column(Interval, nullable=True)

    # `Mapped[str]`, not `Mapped[Tier]`: Postgres returns a string, which compares equal
    # to a StrEnum member but is not it.
    tier: Mapped[str] = mapped_column(String(8), server_default=Tier.WIRE, index=True)

    feed: Mapped[Feed] = relationship(lazy="raise", back_populates="subscription")

    def __str__(self) -> str:
        return self.category or "uncategorised"


def subscribed(feed_id) -> ColumnElement[bool]:
    """Whether an active subscription exists for this feed."""
    return (
        select(Subscription.id)
        .where(Subscription.feed_id == feed_id, Subscription.active.is_(True))
        .exists()
    )


def unexpired(seen) -> ColumnElement[bool]:
    """Whether a row this old is still inside its feed's window."""
    return Subscription.expires_after.is_(None) | (seen >= func.now() - Subscription.expires_after)


def at_least(tier: Tier) -> ColumnElement[bool]:
    """This tier or any above it, so a caller never spells the ordering out itself."""
    return Subscription.tier.in_(TIERS[TIERS.index(tier) :])
