"""The row shape and the keyset every list of items shares: the river, and the archive's shelves."""

import dataclasses
import datetime
import uuid

from sqlalchemy import Select, and_, func, literal, select, tuple_
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
    # The publication a shelf is of, which is the one thing its URL cannot say. A month
    # names itself and the river is not of anything, so both leave this empty.
    shelf: str = ""


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


def listed(settings: KindleSettings):
    """The columns every list of items shows, in no order: search does not want the river's."""
    return held(*shared(), *_marks(kindle.cutoff_from(settings)))


def newest(query: Select) -> Select:
    """The one order the river index is built for, and the one the keyset cursor encodes."""
    return query.order_by(Item.first_seen_at.desc(), dated().desc(), Item.id.desc())


def bounded(limit: int) -> int:
    """A limit the caller asked for, clamped to one a page can afford."""
    return max(1, min(limit, MAX_LIMIT))


def before(seen: datetime.datetime, dated_at: datetime.datetime, item_id: uuid.UUID):
    """The keyset predicate, each key bound to the type of the column it meets."""
    stamp = Item.first_seen_at.type
    return and_(
        # Implied by the row comparison, and the only part of it the river index can use.
        Item.first_seen_at <= literal(seen, stamp),
        tuple_(Item.first_seen_at, dated(), Item.id)
        < tuple_(literal(seen, stamp), literal(dated_at, stamp), literal(item_id, Item.id.type)),
    )


async def page(session: AsyncSession, query: Select, limit: int, shelf: str = "") -> Listing:
    """One page of an already-ordered query, over-fetched by a row to find the cursor."""
    rows = (await session.execute(query.limit(limit + 1))).mappings().all()
    entries = tuple(Entry(**row) for row in rows[:limit])
    last = entries[-1] if len(rows) > limit else None
    return Listing(
        entries=entries,
        cursor=(
            cursor.encode(last.first_seen_at, last.published_at or last.first_seen_at, last.id)
            if last
            else ""
        ),
        updated=await session.scalar(last_poll()),
        shelf=shelf,
    )
