"""The row shape and the keyset every list of items shares: the river, and the archive's shelves."""

import dataclasses
import datetime
import enum
import uuid

from sqlalchemy import Select, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import kindle, training
from old_news.config import KindleSettings
from old_news.db import Feed, Item, ItemVersion, Subscription
from old_news.ui import cursor

DEFAULT_LIMIT = 40
MAX_LIMIT = 100


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    """One row of a list."""

    id: uuid.UUID
    title: str
    url: str
    outlet: str
    author: str
    published_at: datetime.datetime | None
    first_seen_at: datetime.datetime
    read: bool
    # Solid once a book carrying it has gone out; dashed while it is only due to.
    sent: bool
    queued: bool
    # Why a search turned this up, with what matched wrapped in the markers `search`
    # names. Every other list leaves it empty.
    snippet: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Listing:
    """A page of entries, and where the next one starts. An empty cursor is the end."""

    entries: tuple[Entry, ...]
    cursor: str
    # What the masthead carries. It answers "is this working", which is the question a
    # reader actually has, rather than "how much have you missed".
    updated: datetime.datetime | None


def last_poll():
    """The newest successful poll across everything we follow."""
    return select(func.max(Feed.last_success_at)).where(Feed.subscribed)


def shared():
    """The columns both screens show. `canonical_url` wins where the publisher set one."""
    return (
        Item.id.label("id"),
        ItemVersion.title.label("title"),
        func.coalesce(func.nullif(ItemVersion.canonical_url, ""), ItemVersion.url).label("url"),
        Feed.title.label("outlet"),
        ItemVersion.author.label("author"),
        ItemVersion.published_at.label("published_at"),
        Item.first_seen_at.label("first_seen_at"),
        Item.read.label("read"),
    )


def _marks(cutoff: datetime.datetime):
    """Whether an issue has carried this, or is going to."""
    return (
        kindle.sent().label("sent"),
        kindle.queued(cutoff).label("queued"),
    )


def joined(*columns):
    """An item, its head version, the feed it came from and how that is filed."""
    return (
        select(*columns)
        .select_from(Item)
        .join(Item.current_version)
        .join(Feed, Feed.id == Item.feed_id)
        # Outer: unsubscribing must not take an open article away.
        .outerjoin(Subscription, Subscription.feed_id == Feed.id)
    )


def held(*columns):
    """Everything the archive holds. Blocked rows are not held: training threw them out."""
    return joined(*columns).where(~training.blocked(ItemVersion, Item))


def dated():
    """What a tie is broken by: the publisher's date where there is one, ours where there is not."""
    return func.coalesce(ItemVersion.published_at, Item.first_seen_at)


# Matches `IngestSettings.max_backoff_seconds`: the longest a feed goes unpolled with nothing
# properly wrong, so the longest a piece can have been out before we could have found it. At
# the poll ceiling instead it placed under half the river by its date; at this one, three
# quarters. `test_the_ceiling_tracks_the_backoff` is what holds the two together.
SLOWEST_POLL = datetime.timedelta(hours=24)


def placed():
    """Where a row sits: the publisher's date, unless we were too late for that to place it."""
    return func.greatest(dated(), Item.first_seen_at - SLOWEST_POLL)


def listed(settings: KindleSettings):
    """The columns every list of items shows, in no order: search does not want the river's."""
    return held(*shared(), *_marks(kindle.cutoff_from(settings)))


class Order(enum.StrEnum):
    """Which way a list comes back, which is also what its cursor is cut on."""

    # When it was published, held up to the poll ceiling so a piece we were slow to find
    # lands near the top rather than wherever its date would have buried it. A sort, but
    # the river is bounded by its windows and there are a few hundred rows in one.
    PLACED = "placed"
    # When it was published. A feed's first poll backfills a whole catalogue under one
    # afternoon, and an archive that filed it there would be lying about when it was
    # written — so this one is a sort, not a scan.
    PUBLISHED = "published"


def keys(order: Order):
    """The sort keys, most significant first. A cursor holds their values in this order."""
    if order is Order.PLACED:
        return (placed(), Item.first_seen_at, Item.id)
    return (dated(), Item.first_seen_at, Item.id)


def _values(order: Order, row: Entry):
    """The same three facts off a row, in the same order the keys are in."""
    dated_at = row.published_at or row.first_seen_at
    if order is Order.PLACED:
        return (max(dated_at, row.first_seen_at - SLOWEST_POLL), row.first_seen_at, row.id)
    return (dated_at, row.first_seen_at, row.id)


def ordered(query: Select, order: Order) -> Select:
    """Newest first, by whichever of the two clocks the screen goes by."""
    return query.order_by(*(key.desc() for key in keys(order)))


def bounded(limit: int) -> int:
    """A limit the caller asked for, clamped to one a page can afford."""
    return max(1, min(limit, MAX_LIMIT))


def before(order: Order, first: datetime.datetime, second: datetime.datetime, item_id: uuid.UUID):
    """The keyset predicate, each key bound to the type of the column it meets."""
    stamp = Item.first_seen_at.type
    columns = keys(order)
    bounds = (literal(first, stamp), literal(second, stamp), literal(item_id, Item.id.type))
    return tuple_(*columns) < tuple_(*bounds)


async def page(session: AsyncSession, query: Select, limit: int, order: Order) -> Listing:
    """One page of an already-ordered query, over-fetched by a row to find the cursor."""
    rows = (await session.execute(query.limit(limit + 1))).mappings().all()
    entries = tuple(Entry(**row) for row in rows[:limit])
    last = entries[-1] if len(rows) > limit else None
    return Listing(
        entries=entries,
        cursor=cursor.encode(*_values(order, last)) if last else "",
        updated=await session.scalar(last_poll()),
    )
