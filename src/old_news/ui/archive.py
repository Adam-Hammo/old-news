"""The archive: what is held, shelved so that every list off it has an end you can see."""

import dataclasses
import datetime
import uuid

from sqlalchemy import Select, cast, func, literal, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import KindleSettings
from old_news.db import Feed, Item, Subscription, Tier, at_least
from old_news.ui import cursor, entries

MONTH = "YYYY-MM"
UTC = "UTC"

# Postgres carries its own tzdata and it is the copy that does the arithmetic here, so it
# is also the copy that decides what a zone is. Python's `zoneinfo` knows 113 names this
# does not — the legacy aliases — and a browser can still report one of them.
KNOWN_ZONE = text("select exists (select 1 from pg_timezone_names where name = :zone)")


class BadShelf(ValueError):
    """Asked for a shelf the archive cannot have: an unknown month, tier or timezone."""


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
        raise BadShelf(zone)
    return zone


def _tiered(query: Select, tier: str) -> Select:
    if not tier:
        return query
    try:
        return query.where(at_least(Tier(tier)))
    except ValueError as exc:
        raise BadShelf(tier) from exc


def _edges(month: str, zone: str):
    """A month's two instants, so the shelf is a range scan on the river index's own column."""
    # Naive arithmetic, then one conversion, by the same tzdata that labels the months.
    year, _, ordinal = month.partition("-")
    try:
        start = datetime.date(int(year), int(ordinal), 1)
        following = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    except (ValueError, OverflowError) as exc:
        raise BadShelf(month) from exc
    at = (cast(literal(edge.isoformat()), TIMESTAMP) for edge in (start, following))
    return tuple(func.timezone(zone, naive) for naive in at)


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


@db.transactional
async def shelf(
    session: AsyncSession,
    settings: KindleSettings,
    *,
    feed: uuid.UUID | None = None,
    month: str = "",
    tier: str = "",
    after: str = "",
    limit: int = entries.DEFAULT_LIMIT,
    zone: str = UTC,
) -> entries.Listing:
    """One shelf: a publication's run, a month, or both. Never everything — that is the point."""
    if feed is None and not month:
        raise BadShelf("a shelf is a publication or a month")

    query = _tiered(entries.newest(entries.listed(settings)), tier)
    named = ""
    if feed is not None:
        query = query.where(Item.feed_id == feed)
        named = await session.scalar(select(Feed.title).where(Feed.id == feed)) or ""
    if month:
        since, until = _edges(month, await _zoned(session, zone))
        query = query.where(Item.first_seen_at >= since, Item.first_seen_at < until)
    if after:
        query = query.where(entries.before(*cursor.decode(after)))

    return await entries.page(session, query, entries.bounded(limit), shelf=named)
