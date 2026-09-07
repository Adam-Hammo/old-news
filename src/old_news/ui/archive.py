"""The archive: what is held, shelved so that every list off it has an end you can see."""

import dataclasses
import datetime

from sqlalchemy import Select, cast, desc, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import KindleSettings
from old_news.db import Feed, Item, ItemVersion
from old_news.ui import cursor, entries, search
from old_news.ui.query import Named, Query

MONTH = "YYYY-MM"
UTC = "UTC"

# Postgres carries its own tzdata and it is the copy that does the arithmetic here, so it
# is also the copy that decides what a zone is. Python's `zoneinfo` knows 113 names this
# does not — the legacy aliases — and a browser can still report one of them.
KNOWN_ZONE = text("select exists (select 1 from pg_timezone_names where name = :zone)")


class BadZone(ValueError):
    """A timezone Postgres does not know, which is the one thing it decides here."""


@dataclasses.dataclass(frozen=True, slots=True)
class Count:
    """One value of one dimension, and how much of the result it accounts for."""

    name: str
    items: int


@dataclasses.dataclass(frozen=True, slots=True)
# Every dimension is counted with each filter but its own, so the one already picked is
# still a choice you can see.
class Shape:
    """What a query reached, one dimension at a time."""

    publications: tuple[Count, ...]
    months: tuple[Count, ...]
    states: tuple[Count, ...]
    # The masthead is on this screen too, and it asks the same question everywhere.
    updated: datetime.datetime | None


async def _zoned(session: AsyncSession, zone: str) -> str:
    if not await session.scalar(KNOWN_ZONE, {"zone": zone}):
        raise BadZone(zone)
    return zone


# Postgres does the conversion, by the same copy of tzdata that labels the months.
def _instant(on: datetime.date, zone: str):
    """Midnight where the reader is."""
    return func.timezone(zone, cast(literal(on.isoformat()), TIMESTAMP))


# `%` and `_` in a name are the reader's characters, not the pattern's.
LIKE_ESCAPE = str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"})


def _like(columns, name: str):
    """One name against any of the columns it could be typed as."""
    pattern = f"%{name.translate(LIKE_ESCAPE)}%"
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


def _loosely(query: Select, columns, names: tuple[Named, ...]) -> Select:
    """Any of the names asked for, and none of the ones asked against."""
    wanted = [name.value for name in names if not name.excluded]
    against = [name.value for name in names if name.excluded]
    if wanted:
        query = query.where(or_(*(_like(columns, name) for name in wanted)))
    for name in against:
        query = query.where(~_like(columns, name))
    return query


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
    # Title or address: an untitled feed is named by its address on the rail, so that is
    # what gets typed back at us.
    query = _loosely(query, (Feed.title, Feed.url), asked.publications)
    query = _loosely(query, (ItemVersion.author,), asked.authors)
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

    # By publish date, which is what the rail's months are counted on: the two disagreeing
    # is how a 2019 essay comes to sit at the top of a list under a heading saying 2026.
    ordered = entries.ordered(narrowed, entries.Order.PUBLISHED)
    if after:
        ordered = ordered.where(entries.before(entries.Order.PUBLISHED, *cursor.decode(after)))
    return search.Found(
        listing=await entries.page(
            session, ordered, entries.bounded(limit), entries.Order.PUBLISHED
        ),
        total=await session.scalar(select(func.count()).select_from(narrowed.subquery("narrowed")))
        or 0,
    )


# Dropping one dimension is what keeps a facet switchable: with its own filter applied it
# would only ever count the one value already chosen.
def _but(asked: Query, dimension: str) -> Query:
    dropped: dict[str, dict] = {
        "publications": {"publications": ()},
        "states": {"states": ()},
    }
    return dataclasses.replace(asked, **dropped[dimension])


# `_narrowed` leaves the words out, because on the reading path the ranking join applies
# them. Counting has no ranking, so the rail has to apply them itself or it reports the
# whole archive against a result of forty-five.
def _reached(query: Select, asked: Query, zone: str) -> Select:
    """Everything the query reached, words and all."""
    narrowed = _narrowed(query, asked, zone)
    return narrowed.where(search.reaching(asked.wanted)) if asked.wanted else narrowed


def _grouped(asked: Query, zone: str, by, *, order):
    """One dimension's counts over everything the rest of the query reached."""
    counted = _reached(entries.held(by.label("name"), func.count().label("items")), asked, zone)
    # A blank name is a row nobody can click: `from:` with nothing after it is a bad query.
    return counted.group_by("name").having(func.coalesce(by, "") != "").order_by(order)


YEAR = "YYYY"


# Fifty months in a column is not a date facet. Years until the query is inside one, then
# that year's months — the same click that narrows is what drills in, so there is no
# expand-and-collapse to build or to explain.
def _dates(asked: Query) -> tuple[Query, bool]:
    """The query a date facet counts against, and whether it counts in months."""
    # `until` is exclusive, so what decides this is the last day the query takes in: a
    # range from June to next June spans two years and has to be counted in them, or the
    # months of the second one are in the results and nowhere on the rail.
    inside = (
        asked.since is not None
        and asked.until is not None
        and (asked.until - datetime.timedelta(days=1)).year == asked.since.year
    )
    if not inside:
        # Years, over the whole span: switching year has to still be a choice you can see.
        return dataclasses.replace(asked, since=None, until=None), False
    # Months of the year already chosen. Widened to that year rather than dropped, or the
    # facet lists every month the archive has ever held and the drill goes nowhere.
    year = asked.since.year
    return (
        dataclasses.replace(
            asked, since=datetime.date(year, 1, 1), until=datetime.date(year + 1, 1, 1)
        ),
        True,
    )


def _period(zone: str, monthly: bool):
    local = func.timezone(zone, entries.dated())
    return func.to_char(
        func.date_trunc("month" if monthly else "year", local), MONTH if monthly else YEAR
    )


def _states(asked: Query, zone: str):
    """All four at once: they are four readings of two columns, not four groups."""
    counted = {
        "read": Item.read.is_(True),
        "unread": Item.read.is_(False),
        "finished": Item.finished_at.is_not(None),
        "unfinished": Item.finished_at.is_(None),
    }
    return _reached(
        entries.held(*(func.count().filter(where).label(name) for name, where in counted.items())),
        asked,
        zone,
    )


@db.transactional
async def shape(session: AsyncSession, *, asked: Query, zone: str = UTC) -> Shape:
    """The rail: what is in what the query reached, and what switching one part would give."""
    where = await _zoned(session, zone)
    named = func.coalesce(func.nullif(Feed.title, ""), Feed.url)
    publications = await session.execute(
        # Biggest first: which publications an archive is mostly made of is the answer.
        _grouped(_but(asked, "publications"), where, named, order=desc("items"))
    )
    dated, monthly = _dates(asked)
    months = await session.execute(
        # Newest first. A period is a place on a line and reading them by size is no
        # ordering at all — `YYYY` and `YYYY-MM` both sort as text exactly as they sort
        # as dates.
        _grouped(dated, where, _period(where, monthly), order=desc("name"))
    )
    states = (await session.execute(_states(_but(asked, "states"), where))).mappings().one()

    return Shape(
        publications=tuple(Count(**row) for row in publications.mappings()),
        months=tuple(Count(**row) for row in months.mappings()),
        states=tuple(Count(name=name, items=items) for name, items in states.items()),
        updated=await session.scalar(entries.last_poll()),
    )
