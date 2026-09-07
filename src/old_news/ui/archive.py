"""The archive: what is held, shelved so that every list off it has an end you can see."""

import dataclasses
import datetime
import uuid

from sqlalchemy import Select, cast, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import KindleSettings
from old_news.db import Feed, Item, ItemVersion, Subscription
from old_news.ui import cursor, entries, search
from old_news.ui.query import Query

MONTH = "YYYY-MM"
UTC = "UTC"

# Postgres carries its own tzdata and it is the copy that does the arithmetic here, so it
# is also the copy that decides what a zone is. Python's `zoneinfo` knows 113 names this
# does not — the legacy aliases — and a browser can still report one of them.
KNOWN_ZONE = text("select exists (select 1 from pg_timezone_names where name = :zone)")


class BadZone(ValueError):
    """A timezone Postgres does not know, which is the one thing it decides here."""


@dataclasses.dataclass(frozen=True, slots=True)
class Volume:
    """One bound volume, and how much is in it."""

    month: str
    items: int


@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    """One publication's whole run. `dropped` is a feed no longer polled, not one lost."""

    feed_id: uuid.UUID
    title: str
    url: str
    tier: str
    dropped: bool
    items: int
    latest: datetime.datetime


@dataclasses.dataclass(frozen=True, slots=True)
class Contents:
    """What the archive holds, on two shelves. Both counts are of the same rows."""

    items: int
    months: tuple[Volume, ...]
    feeds: tuple[Run, ...]
    # The masthead is on this screen too, and it asks the same question everywhere.
    updated: datetime.datetime | None


async def _zoned(session: AsyncSession, zone: str) -> str:
    if not await session.scalar(KNOWN_ZONE, {"zone": zone}):
        raise BadZone(zone)
    return zone


@db.transactional
async def contents(session: AsyncSession, *, zone: str = UTC) -> Contents:
    """The contents page. Months are grouped in the reader's own zone, or they read wrong."""
    local = func.timezone(await _zoned(session, zone), Item.first_seen_at)
    volumes = await session.execute(
        entries.held(
            func.to_char(func.date_trunc("month", local), MONTH).label("month"),
            func.count().label("items"),
        )
        .group_by("month")
        .order_by(func.min(Item.first_seen_at).desc())
    )
    runs = await session.execute(
        entries.held(
            Feed.id.label("feed_id"),
            Feed.title.label("title"),
            Feed.url.label("url"),
            func.coalesce(Subscription.tier, "").label("tier"),
            func.coalesce(Subscription.active, False).is_(False).label("dropped"),
            func.count().label("items"),
            func.max(Item.first_seen_at).label("latest"),
        )
        .group_by(Feed.id, Feed.title, Feed.url, Subscription.tier, Subscription.active)
        .order_by(func.count().desc())
    )
    months = tuple(Volume(**row) for row in volumes.mappings())
    return Contents(
        items=sum(volume.items for volume in months),
        months=months,
        feeds=tuple(Run(**row) for row in runs.mappings()),
        updated=await session.scalar(entries.last_poll()),
    )


# Postgres does the conversion, by the same copy of tzdata that labels the months.
def _instant(on: datetime.date, zone: str):
    """Midnight where the reader is."""
    return func.timezone(zone, cast(literal(on.isoformat()), TIMESTAMP))


# `%` and `_` in a name are the reader's characters, not the pattern's.
LIKE_ESCAPE = str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"})


def _loosely(column, names: tuple[str, ...]):
    """Any of these names, matched the way somebody types a publication rather than files it."""
    return or_(*(column.ilike(f"%{name.translate(LIKE_ESCAPE)}%", escape="\\") for name in names))


STATES = {
    "read": lambda: Item.read.is_(True),
    "unread": lambda: Item.read.is_(False),
    "finished": lambda: Item.finished_at.is_not(None),
    "unfinished": lambda: Item.finished_at.is_(None),
}


# The words decide the order and only the order, so every one of these applies whether
# any were typed or not.
def _narrowed(query: Select, asked: Query, zone: str) -> Select:
    """Everything the reader asked for that is not words."""
    if asked.publications:
        query = query.where(_loosely(Feed.title, asked.publications))
    if asked.authors:
        query = query.where(_loosely(ItemVersion.author, asked.authors))
    # On the publisher's date where there is one: a feed's first poll backfills a whole
    # back catalogue under today, and `after:2019` has to still reach a 2019 piece.
    if asked.since is not None:
        query = query.where(entries.dated() >= _instant(asked.since, zone))
    if asked.until is not None:
        query = query.where(entries.dated() < _instant(asked.until, zone))
    for state in asked.states:
        query = query.where(STATES[state]())
    if excluded := tuple(term for term in asked.terms if term.excluded):
        query = query.where(search.without(excluded))
    return query


@db.transactional
async def held(
    session: AsyncSession,
    settings: KindleSettings,
    *,
    asked: Query,
    after: str = "",
    limit: int = entries.DEFAULT_LIMIT,
    zone: str = UTC,
) -> search.Found:
    # One path in. The only thing the words decide is the order, and with none of them
    # there is no relevance to sort on, so the archive falls back to its own cursor.
    """Everything the archive holds that the query reaches."""
    narrowed = _narrowed(entries.listed(settings), asked, await _zoned(session, zone))

    if asked.ranked:
        return await search.deep(session, narrowed, asked, after=after, limit=limit)

    ordered = entries.newest(narrowed)
    if after:
        ordered = ordered.where(entries.before(*cursor.decode(after)))
    return search.Found(
        listing=await entries.page(session, ordered, entries.bounded(limit)),
        total=await session.scalar(select(func.count()).select_from(narrowed.subquery("narrowed")))
        or 0,
    )
