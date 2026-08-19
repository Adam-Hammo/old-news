import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ColumnElement, ForeignKey, Text, select, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey

if TYPE_CHECKING:
    from old_news.db.models.feed import Feed


class Subscription(UUIDPrimaryKey, Base):
    """Following a feed, as distinct from the feed itself.

    `active` is a choice; `Feed.suspended` is the poller giving up. Keeping them
    apart means unsubscribing never looks like a broken feed in the numbers.

    One-to-one is enforced by the unique feed_id rather than by sharing the
    feed's primary key: same guarantee today, and relaxing it to many-per-feed
    later is dropping a constraint rather than replacing a key.
    """

    __tablename__ = "subscriptions"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), unique=True
    )
    category: Mapped[str] = mapped_column(Text, server_default="", index=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), index=True)
    added_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    feed: Mapped[Feed] = relationship(lazy="raise", back_populates="subscription")

    def __str__(self) -> str:
        return self.category or "uncategorised"


def subscribed(feed_id) -> ColumnElement[bool]:
    """Whether an active subscription exists for this feed.

    Written once and reached from both `Feed.subscribed` and `Item.subscribed`, because
    every sweep needs it and an inner join to `subscriptions` for one boolean reads worse
    at four call sites than the predicate does.
    """
    return (
        select(Subscription.id)
        .where(Subscription.feed_id == feed_id, Subscription.active.is_(True))
        .exists()
    )
