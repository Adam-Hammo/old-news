"""What the reader has said it does not want, as a clause a sweep can put in its WHERE."""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from old_news import db
from old_news.db import Dimension, Feed, Filter, FilterSource, Item, ItemVersion


class UnknownFeed(ValueError):
    """A filter scoped to a feed that is not in the database."""


@dataclass(frozen=True, slots=True)
class Blocking:
    """One filter, as a screen for managing them needs it."""

    id: uuid.UUID
    dimension: str
    pattern: str
    # Null is every feed.
    feed_id: uuid.UUID | None
    # Its title, or its address where it has none. Empty when the filter is global.
    feed: str
    source: str
    note: str


def _contains(
    haystack: InstrumentedAttribute[str], needle: InstrumentedAttribute[str]
) -> ColumnElement[bool]:
    """Case-insensitive substring. strpos, not LIKE: a column pattern can't be escaped."""
    return func.strpos(func.lower(haystack), func.lower(needle)) > 0


def _matches(rule: type[Filter], version: type[ItemVersion]) -> ColumnElement[bool]:
    """One dimension per branch, so adding one is a branch and a migration together."""
    return or_(
        and_(rule.dimension == Dimension.TITLE_PHRASE, _contains(version.title, rule.pattern)),
        and_(rule.dimension == Dimension.URL_PATTERN, _contains(version.url, rule.pattern)),
    )


def blocked(version: type[ItemVersion], item: type[Item]) -> ColumnElement[bool]:
    """True where a filter matches this version. A filter with no feed is global."""
    return exists(
        select(Filter.id).where(
            or_(Filter.feed_id.is_(None), Filter.feed_id == item.feed_id),
            _matches(Filter, version),
        )
    )


@db.transactional
async def listing(session: AsyncSession) -> tuple[Blocking, ...]:
    """Every filter, global ones first."""
    rows = await session.execute(
        select(
            Filter.id,
            Filter.dimension,
            Filter.pattern,
            Filter.feed_id,
            func.coalesce(func.nullif(Feed.title, ""), Feed.url, ""),
            Filter.source,
            Filter.note,
        )
        .outerjoin(Feed, Feed.id == Filter.feed_id)
        .order_by(Filter.feed_id.is_not(None), Feed.title, Filter.dimension, Filter.pattern)
    )
    return tuple(Blocking(*row) for row in rows.all())


@db.transactional
async def add(
    session: AsyncSession, dimension: str, pattern: str, *, feed_id: uuid.UUID | None, note: str
) -> bool:
    """Block whatever matches from now on. False if that exact filter is already there."""
    if feed_id is not None and await session.get(Feed, feed_id) is None:
        raise UnknownFeed(feed_id)
    added = await session.scalar(
        insert(Filter)
        .values(
            dimension=dimension,
            pattern=pattern,
            feed_id=feed_id,
            source=FilterSource.HAND,
            note=note,
        )
        .on_conflict_do_nothing()
        .returning(Filter.id)
    )
    return added is not None


@db.transactional
async def remove(session: AsyncSession, filter_id: uuid.UUID) -> bool:
    """Stop blocking. What it hid comes back, since nothing it matched was ever deleted."""
    removed = await session.scalar(
        delete(Filter).where(Filter.id == filter_id).returning(Filter.id)
    )
    return removed is not None
