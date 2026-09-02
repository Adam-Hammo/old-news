import datetime
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    Index,
    Integer,
    Text,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of, run_of

# The only answer that is permanent on its own.
PERMANENTLY_GONE = 410


class PollOutcome(enum.StrEnum):
    """What a poll turned out to be. Only `FAILED` backs a feed off."""

    OK = "ok"
    # A 304 is a healthy poll that happened to carry nothing.
    NOT_MODIFIED = "not_modified"
    # Not a failure: dropping the rule brings the feed back.
    DISALLOWED = "disallowed"
    FAILED = "failed"


class FeedPoll(UUIDPrimaryKey, Base):
    """One visit to one feed, as it happened. Append-only; the feed row says what happens next."""

    __tablename__ = "feed_polls"
    __table_args__ = (
        CheckConstraint(one_of("outcome", PollOutcome), name="known_outcome"),
        # Counting back to the last non-failure reads this, newest first.
        Index("ix_feed_polls_feed_polled", "feed_id", text("polled_at DESC")),
    )

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE")
    )
    polled_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    outcome: Mapped[str] = mapped_column(Text)
    # 0 when the transport failed, which is not an HTTP status at all.
    status: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str] = mapped_column(Text, server_default="")
    new_items: Mapped[int] = mapped_column(Integer, server_default="0")

    def __str__(self) -> str:
        return f"{self.outcome} {self.status}"


def consecutive_failures(feed_id) -> ColumnElement[int]:
    """Failed polls since the last one that was not a failure."""
    return run_of(
        FeedPoll,
        at=lambda poll: poll.polled_at,
        scope=lambda poll: poll.feed_id == feed_id,
        counts=lambda poll: poll.outcome == PollOutcome.FAILED,
        # A 304 and a robots refusal both end a run. Neither says the publisher broke.
        resets=lambda poll: poll.outcome != PollOutcome.FAILED,
    ).length


def gone(feed_id) -> ColumnElement[bool]:
    """Whether the publisher has ever answered 410. Needs no threshold, unlike giving up."""
    return (
        select(FeedPoll.id)
        .where(FeedPoll.feed_id == feed_id, FeedPoll.status == PERMANENTLY_GONE)
        .exists()
    )
