"""What a reader asks for: a river, one article, and the sections that slice it."""

import dataclasses
import datetime
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import KindleSettings
from old_news.db import (
    ExtractionSource,
    ImageRole,
    Item,
    ItemVersion,
    Subscription,
    item_reading,
    unexpired,
)
from old_news.ui import cursor, entries


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
    saved: bool
    comments_url: str
    versions: int
    # The kicker. A row cannot carry one — a section is a set of feeds and a row would be
    # claiming a topic the model does not hold — but one article has exactly one feed.
    section: str
    # The one picture fetched unasked, served from what is held. Empty where there is
    # none, or where the reading already carries it.
    lead: str
    lead_alt: str
    # So the page can hold the picture's room before it arrives. Zero where it did not open.
    lead_width: int
    lead_height: int


@db.transactional
async def river(
    session: AsyncSession,
    settings: KindleSettings,
    *,
    section: str = "",
    after: str = "",
    limit: int = entries.DEFAULT_LIMIT,
) -> entries.Listing:
    """A page of the river, newest first by when a thing was written, then by when we saw it."""
    query = entries.ordered(
        entries.listed(settings).where(
            Subscription.active.is_(True), unexpired(Item.first_seen_at, ItemVersion.published_at)
        ),
        entries.Order.PLACED,
    )
    if section:
        query = query.where(Subscription.category == section)
    if after:
        query = query.where(entries.before(entries.Order.PLACED, *cursor.decode(after)))

    return await entries.page(session, query, entries.bounded(limit), entries.Order.PLACED)


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


def _lead(held: tuple[extract.Held, ...], readings: str) -> extract.Held | None:
    """The hero, unless a reading already sets it — some publishers put it in both."""
    for picture in held:
        if picture.role == ImageRole.LEAD and not extract.carries(readings, picture.url):
            return picture
    return None


@db.transactional
async def _reading_row(session: AsyncSession, item_id: uuid.UUID) -> dict | None:
    """One item and its text. Not scoped to a subscription: an open article outlives one."""
    query = entries.joined(
        *entries.shared(),
        Item.reading_body.label("body"),
        item_reading(ExtractionSource.FEED).label("feed"),
        item_reading(ExtractionSource.PAGE).label("page"),
        ItemVersion.comments_url.label("comments_url"),
        Item.version_count.label("versions"),
        Item.saved_at.is_not(None).label("saved"),
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
    lead = _lead(held, feed + page)
    stored = await extract.bytes_of(lead.capture_id) if lead else None
    width, height = extract.measure(stored[0]) if stored else (0, 0)
    local = _local(held)
    return Article(
        feed_body=_pointed_at_us(feed, local),
        page_body=_pointed_at_us(page, local),
        reading=ExtractionSource.FEED if body == feed else ExtractionSource.PAGE,
        lead=f"/{IMAGES}/{lead.capture_id}/" if lead else "",
        lead_alt=lead.alt if lead else "",
        lead_width=width,
        lead_height=height,
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


@db.transactional
async def mark_saved(session: AsyncSession, item_id: uuid.UUID) -> datetime.datetime | None:
    """Put an item in the saved collection. None if there is no such item."""
    saved = await session.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(saved_at=func.coalesce(Item.saved_at, func.now()))
        .returning(Item.saved_at)
    )
    return saved.scalar_one_or_none()


@db.transactional
async def unsave(session: AsyncSession, item_id: uuid.UUID) -> bool:
    """Take an item out of the saved collection, keeping what was captured for it."""
    found = await session.execute(
        update(Item).where(Item.id == item_id).values(saved_at=None).returning(Item.id)
    )
    return found.scalar_one_or_none() is not None
