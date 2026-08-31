"""What a reader asks for: a river, one article, and the sections that slice it."""

import dataclasses
import datetime
import uuid

from sqlalchemy import RowMapping, and_, func, literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, training
from old_news.db import ExtractionSource, Feed, Item, ItemVersion, Subscription, item_reading
from old_news.ui import cursor
from old_news.ui.deck import deck

DECK_CHARS = 220
# Enough of the teaser to tell "this is the first paragraph" from "this is a summary".
STANDFIRST_MATCH = 100
# Generously more than the deck needs, so stripping marks cannot leave it short.
DECK_SOURCE_CHARS = DECK_CHARS * 4

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
    deck: str
    published_at: datetime.datetime | None
    first_seen_at: datetime.datetime
    read: bool


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
    deck: str
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


def _last_poll():
    """The newest successful poll across everything we follow."""
    return (
        select(func.max(Feed.last_success_at))
        .select_from(Feed)
        .join(Subscription, and_(Subscription.feed_id == Feed.id, Subscription.active.is_(True)))
        .scalar_subquery()
    )


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


def _reading(*columns):
    """Items joined to their head version, the feed they came from, and how it is filed."""
    return (
        select(*columns)
        # Columns from three tables, so the left side of the first join is not inferable.
        .select_from(Item)
        .join(ItemVersion, and_(ItemVersion.item_id == Item.id, ItemVersion.is_head))
        .join(Feed, Feed.id == Item.feed_id)
        # Outer: unsubscribing must not take an open article away.
        .outerjoin(Subscription, Subscription.feed_id == Feed.id)
    )


def _before(seen: datetime.datetime, item_id: uuid.UUID):
    """The keyset predicate, each half bound to the type of the column it meets."""
    return tuple_(Item.first_seen_at, Item.id) < tuple_(
        literal(seen, Item.first_seen_at.type), literal(item_id, Item.id.type)
    )


def _entry(row: RowMapping) -> Entry:
    fields = dict(row)
    return Entry(deck=deck(fields.pop("body"), DECK_CHARS), **fields)


@db.transactional
async def river(
    session: AsyncSession,
    *,
    section: str = "",
    after: str = "",
    limit: int = DEFAULT_LIMIT,
) -> River:
    """A page of the river, newest first by when we first saw it — never the publisher's date."""
    limit = max(1, min(limit, MAX_LIMIT))

    query = (
        _reading(*_shared(), func.left(Item.reading_body, DECK_SOURCE_CHARS).label("body"))
        .where(Subscription.active.is_(True), ~training.blocked(ItemVersion, Item))
        .order_by(Item.first_seen_at.desc(), Item.id.desc())
        .limit(limit + 1)
    )
    if section:
        query = query.where(Subscription.category == section)
    if after:
        query = query.where(_before(*cursor.decode(after)))

    rows = (await session.execute(query)).mappings().all()
    entries = tuple(_entry(row) for row in rows[:limit])
    more = len(rows) > limit
    return River(
        entries=entries,
        cursor=cursor.encode(entries[-1].first_seen_at, entries[-1].id) if more else "",
        updated=await session.scalar(select(_last_poll())),
    )


@db.transactional
async def article(session: AsyncSession, item_id: uuid.UUID) -> Article | None:
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
    if row is None:
        return None

    fields = dict(row)
    feed, page, body = fields.pop("feed"), fields.pop("page"), fields.pop("body")
    return Article(
        deck=_standfirst(feed, body),
        feed_body=feed,
        page_body=page,
        reading=ExtractionSource.FEED if body == feed else ExtractionSource.PAGE,
        **fields,
    )


def _standfirst(teaser: str, body: str) -> str:
    """The feed's teaser, unless the article simply opens with it."""
    opening = teaser.strip()[:STANDFIRST_MATCH]
    if not opening or body.strip().startswith(opening):
        return ""
    return deck(teaser[:DECK_SOURCE_CHARS], DECK_CHARS)


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
