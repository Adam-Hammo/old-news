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
    and_,
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

# The longest window there is, and what a new feed gets. Nothing stays in the river
# forever: keeping it is the archive's job, not the window's.
LONGEST_WINDOW = datetime.timedelta(days=30)

# A floor under how late a piece may arrive and still count as new. A window can be shorter
# than a poll is legitimately behind, and a publisher down for a few days is retried across
# all of them — dropping is permanent, so this is generous where `ui.entries.SLOWEST_POLL`,
# which only moves a row, is tight.
SLOWEST_ARRIVAL = datetime.timedelta(days=7)

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
    # Postgres does the arithmetic.
    expires_after: Mapped[datetime.timedelta] = mapped_column(
        Interval, server_default=text(f"interval '{LONGEST_WINDOW.days} days'")
    )

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


def new_when_seen(seen, published) -> ColumnElement[bool]:
    """Whether the publisher's date was inside the tolerance at the moment we first saw it."""
    tolerance = func.greatest(Subscription.expires_after, SLOWEST_ARRIVAL)
    return func.coalesce(published, seen) >= seen - tolerance


def unexpired(seen, published) -> ColumnElement[bool]:
    """Whether a row is still in the river: seen inside the window, and new when we saw it."""
    return and_(
        seen >= func.now() - Subscription.expires_after,
        new_when_seen(seen, published),
    )


def at_least(tier: Tier) -> ColumnElement[bool]:
    """This tier or any above it, so a caller never spells the ordering out itself."""
    return Subscription.tier.in_(TIERS[TIERS.index(tier) :])
