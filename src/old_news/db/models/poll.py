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
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, aliased, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of

# The publisher saying the feed is gone for good, which is the only answer that is
# permanent on its own.
PERMANENTLY_GONE = 410


class PollOutcome(enum.StrEnum):
    """What a poll turned out to be. Only `FAILED` backs a feed off."""

    OK = "ok"
    # A 304. The feed answered and had nothing new, which is a healthy poll.
    NOT_MODIFIED = "not_modified"
    # robots.txt names this feed. Not a failure — dropping the rule brings it back.
    DISALLOWED = "disallowed"
    FAILED = "failed"


class FeedPoll(UUIDPrimaryKey, Base):
    """One visit to one feed, as it happened.

    Append-only. The feed row is a cursor saying what happens next; this is the record
    of what already did, which `feeds.last_error` used to overwrite once per poll.
    """

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

    @hybrid_property
    def failed(self) -> bool:
        return self.outcome == PollOutcome.FAILED

    @failed.inplace.expression
    @classmethod
    def _failed_expression(cls):
        return cls.outcome == PollOutcome.FAILED

    def __str__(self) -> str:
        return f"{self.outcome} {self.status}"


def consecutive_failures(feed_id) -> ColumnElement[int]:
    """Failed polls since the last one that was not a failure.

    Derived rather than counted up in a column: the log is the record, and a counter
    beside it is a second copy that can only ever disagree. A 304 and a robots refusal
    both end a run — neither says the publisher is broken.
    """
    # Aliased and correlated explicitly. Both halves select from `feed_polls`, so
    # without this SQLAlchemy folds the inner `max` into the outer WHERE and Postgres
    # rejects the aggregate.
    earlier = aliased(FeedPoll)
    last_good = (
        select(func.max(earlier.polled_at))
        .where(earlier.feed_id == feed_id, earlier.outcome != PollOutcome.FAILED)
        .correlate_except(earlier)
        .scalar_subquery()
    )
    return (
        select(func.count())
        .select_from(FeedPoll)
        .where(
            FeedPoll.feed_id == feed_id,
            FeedPoll.outcome == PollOutcome.FAILED,
            last_good.is_(None) | (FeedPoll.polled_at > last_good),
        )
        .correlate_except(FeedPoll)
        .scalar_subquery()
    )


def gone(feed_id) -> ColumnElement[bool]:
    """Whether the publisher has ever answered 410.

    The one permanent answer a feed can give, so it needs no threshold and no config —
    unlike giving up after N failures, which is our policy rather than their statement
    and so is applied where the settings that define it already are.
    """
    return (
        select(FeedPoll.id)
        .where(FeedPoll.feed_id == feed_id, FeedPoll.status == PERMANENTLY_GONE)
        .exists()
    )
