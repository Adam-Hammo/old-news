"""What a reader asks for: a river, one article, and the sections that slice it."""

import dataclasses
import datetime
import uuid

from sqlalchemy import and_, func, literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract, kindle, training
from old_news.config import KindleSettings
from old_news.db import (
    ExtractionSource,
    Feed,
    ImageRole,
    Item,
    ItemVersion,
    Subscription,
    item_reading,
    unexpired,
)
from old_news.ui import cursor

DEFAULT_LIMIT = 40
MAX_LIMIT = 100


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    """One row of the river."""

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


@dataclasses.dataclass(frozen=True, slots=True)
class River:
    """A page of entries, and where the next one starts. An empty cursor is the end."""

    entries: tuple[Entry, ...]
    cursor: str
    # What the masthead carries. It answers "is this working", which is the question a
    # reader actually has, rather than "how much have you missed".
    updated: datetime.datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class Article:
    """One item, with every reading held for it."""

    id: uuid.UUID
    title: str
    url: str
    outlet: str
    author: str
    # Both readings and which of them opens, so a reader can cross to the other.
    feed_body: str
    page_body: str
    reading: str
    published_at: datetime.datetime | None
    first_seen_at: datetime.datetime
    read: bool
    comments_url: str
    versions: int
    # The kicker. A row cannot carry one — a section is a set of feeds and a row would be
    # claiming a topic the model does not hold — but one article has exactly one feed.
    section: str
    # The one picture fetched unasked, served from what is held. Empty where there is
    # none, or where the reading already carries it.
    lead: str
    lead_alt: str


def _last_poll():
    """The newest successful poll across everything we follow."""
    return select(func.max(Feed.last_success_at)).where(Feed.subscribed)


def _shared():
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


def _reading(*columns):
    """Items joined to their head version, the feed they came from, and how it is filed."""
    return (
        select(*columns)
        .select_from(Item)
        .join(Item.current_version)
        .join(Feed, Feed.id == Item.feed_id)
        # Outer: unsubscribing must not take an open article away.
        .outerjoin(Subscription, Subscription.feed_id == Feed.id)
    )


def _dated():
    """What a tie is broken by: the publisher's date where there is one, ours where there is not."""
    return func.coalesce(ItemVersion.published_at, Item.first_seen_at)


def _before(seen: datetime.datetime, dated: datetime.datetime, item_id: uuid.UUID):
    """The keyset predicate, each key bound to the type of the column it meets."""
    stamp = Item.first_seen_at.type
    return and_(
        # Implied by the row comparison, and the only part of it the river index can use.
        Item.first_seen_at <= literal(seen, stamp),
        tuple_(Item.first_seen_at, _dated(), Item.id)
        < tuple_(literal(seen, stamp), literal(dated, stamp), literal(item_id, Item.id.type)),
    )


def _resume(entry: Entry) -> str:
    """Where a page stopped, in the three keys it was ordered by."""
    return cursor.encode(entry.first_seen_at, entry.published_at or entry.first_seen_at, entry.id)


@db.transactional
async def river(
    session: AsyncSession,
    settings: KindleSettings,
    *,
    section: str = "",
    after: str = "",
    limit: int = DEFAULT_LIMIT,
    archive: bool = False,
) -> River:
    """A page of the river, newest first by when we first saw it, then by the publisher's date."""
    limit = max(1, min(limit, MAX_LIMIT))

    query = (
        _reading(*_shared(), *_marks(kindle.cutoff_from(settings)))
        .where(Subscription.active.is_(True), ~training.blocked(ItemVersion, Item))
        .order_by(Item.first_seen_at.desc(), _dated().desc(), Item.id.desc())
        .limit(limit + 1)
    )
    # A bound on the leading column of the river index, so the cutoff costs less than
    # no cutoff. The archive is the same query with the door left open.
    if not archive:
        query = query.where(unexpired(Item.first_seen_at))
    if section:
        query = query.where(Subscription.category == section)
    if after:
        query = query.where(_before(*cursor.decode(after)))

    rows = (await session.execute(query)).mappings().all()
    entries = tuple(Entry(**row) for row in rows[:limit])
    more = len(rows) > limit
    return River(
        entries=entries,
        cursor=_resume(entries[-1]) if more else "",
        updated=await session.scalar(_last_poll()),
    )


# What the article screen asks for a picture by. The reader's own prefix, not the
# publisher's: the bytes are held and the publisher's copy rots.
IMAGES = "images"


def _local(held: tuple[extract.Held, ...]) -> dict[str, str]:
    return {picture.url: f"/{IMAGES}/{picture.capture_id}/" for picture in held}


def _pointed_at_us(body: str, local: dict[str, str]) -> str:
    """Point what is held at the copy we hold. What is not stays with the publisher."""
    for url, served in local.items():
        body = body.replace(f"]({url})", f"]({served})")
    return body


def _lead(held: tuple[extract.Held, ...], readings: str) -> tuple[str, str]:
    """The hero, unless a reading already sets it — some publishers put it in both."""
    for picture in held:
        if picture.role == ImageRole.LEAD and f"]({picture.url})" not in readings:
            return f"/{IMAGES}/{picture.capture_id}/", picture.alt
    return "", ""


@db.transactional
async def _reading_row(session: AsyncSession, item_id: uuid.UUID) -> dict | None:
    """One item and its text. Not scoped to a subscription: an open article outlives one."""
    query = _reading(
        *_shared(),
        Item.reading_body.label("body"),
        item_reading(ExtractionSource.FEED).label("feed"),
        item_reading(ExtractionSource.PAGE).label("page"),
        ItemVersion.comments_url.label("comments_url"),
        Item.version_count.label("versions"),
        func.coalesce(Subscription.category, "").label("section"),
    ).where(Item.id == item_id)

    row = (await session.execute(query)).mappings().one_or_none()
    return None if row is None else dict(row)


async def article(item_id: uuid.UUID) -> Article | None:
    """The article, with anything we hold a picture for pointed at our own copy."""
    fields = await _reading_row(item_id)
    if fields is None:
        return None

    feed, page, body = fields.pop("feed"), fields.pop("page"), fields.pop("body")
    # Its own transaction, because the reading and the pictures are two queries.
    held = await extract.held_for([item_id])
    lead, lead_alt = _lead(held, feed + page)
    local = _local(held)
    return Article(
        feed_body=_pointed_at_us(feed, local),
        page_body=_pointed_at_us(page, local),
        reading=ExtractionSource.FEED if body == feed else ExtractionSource.PAGE,
        lead=lead,
        lead_alt=lead_alt,
        **fields,
    )


async def image(capture_id: uuid.UUID) -> tuple[bytes, str] | None:
    """The bytes behind one picture. None where nothing usable is held for it."""
    return await extract.bytes_of(capture_id)


@db.transactional
async def sections(session: AsyncSession) -> tuple[str, ...]:
    """The categories worth a tab. An unfiled feed has none and shows only in the whole river."""
    found = await session.execute(
        select(Subscription.category)
        .where(Subscription.active.is_(True), Subscription.category != "")
        .distinct()
        .order_by(Subscription.category)
    )
    return tuple(found.scalars())


@db.transactional
async def mark_opened(session: AsyncSession, item_id: uuid.UUID) -> datetime.datetime | None:
    """Record the first time an item was opened. None if there is no such item."""
    opened = await session.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(read=True, read_at=func.coalesce(Item.read_at, func.now()))
        .returning(Item.read_at)
    )
    return opened.scalar_one_or_none()


@db.transactional
async def mark_finished(session: AsyncSession, item_id: uuid.UUID) -> datetime.datetime | None:
    """Record reaching the bottom of an article, which is what stops an issue carrying it."""
    finished = await session.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(
            read=True,
            read_at=func.coalesce(Item.read_at, func.now()),
            finished_at=func.coalesce(Item.finished_at, func.now()),
        )
        .returning(Item.finished_at)
    )
    return finished.scalar_one_or_none()
