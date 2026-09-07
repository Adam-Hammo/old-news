"""The index. Every call into `paradedb` is here, and it answers a parsed query."""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ARRAY, ColumnElement, Select, and_, case, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import TEXT
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from old_news import extract
from old_news.db import Extraction, Item, ItemVersion
from old_news.ui import entries
from old_news.ui.query import BadQuery, Query, Term

# Around what matched, and not spelt in markup: the fragment is prose by the time these
# go in, and anything punctuation-shaped would read as the publisher's. The client splits
# on them to set what matched in bold.
OPEN = "\x02"
CLOSE = "\x03"

# Enough of the sentence to recognise the article by. The reader has the headline already.
SNIPPET_CHARS = 220

# How much of the run-up to keep, so the matched word is not the first thing in the window.
LEAD_IN = 60

WORD = re.compile(r"\w+")

# Nobody pages to the five hundredth match; a search that deep is a search to retype. The
# bound is also what keeps a hand-typed `after` from reaching Postgres as an overflow.
MAX_DEPTH = 1000


@dataclasses.dataclass(frozen=True, slots=True)
class Found:
    """What matched, and how much did. The count is what makes narrowing a decision."""

    listing: entries.Listing
    total: int


def _field(name: str):
    """`paradedb.match` takes its own type here, and a bound parameter arrives untyped."""
    return cast(literal(name), TEXT)


# `paradedb.match(field, value, tokenizer, distance, transposition_cost_one, prefix,
# conjunction_mode)`. Postgres named arguments have no SQLAlchemy spelling, so the four
# in between are passed as the NULLs they default to anyway.
DEFAULTS = (None, None, None, None)


def _asked(field: str, term: Term):
    """One term as the index's own question: adjacent where it was quoted, a word otherwise."""
    if term.phrase:
        return func.paradedb.phrase(_field(field), cast(pg_array(term.words), ARRAY(TEXT)))
    return func.paradedb.match(_field(field), term.words[0], *DEFAULTS, True)


# One predicate per term rather than one array of them: a bound array of
# `searchqueryinput` has no SQLAlchemy spelling, and composing in SQL needs none.
def _reaches(key: InstrumentedAttribute, field: str, terms: Sequence[Term]):
    """Whether this row's index answers every one of them."""
    return and_(*(key.op("@@@")(_asked(field, term)) for term in terms))


def _touches(key: InstrumentedAttribute, field: str, terms: Sequence[Term]):
    """Whether it answers any of them, which is what an exclusion is asked in terms of."""
    return or_(*(key.op("@@@")(_asked(field, term)) for term in terms))


def _bodies(*columns):
    return (
        select(*columns)
        .select_from(Extraction)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
    )


# Either field disqualifies: `-liberal` means the piece is not about them, not that the
# headline is not.
def without(terms: Sequence[Term]) -> ColumnElement[bool]:
    """Items where none of these appears, in the headline or in the reading."""
    titled = select(ItemVersion.item_id).where(
        ItemVersion.is_head, _touches(ItemVersion.id, "title", terms)
    )
    bodied = _bodies(ItemVersion.item_id).where(
        ItemVersion.is_head, _touches(Extraction.id, "body", terms)
    )
    return Item.id.not_in(titled.union(bodied))


def _hits(terms: Sequence[Term]):
    """Every item the terms reach, by headline and by reading, as one set of ids."""
    # Head versions only: a liveblog rewrites its headline, and matching the one it
    # replaced surfaces an article whose headline says something else.
    titles = select(
        ItemVersion.item_id.label("item_id"),
        literal(True).label("in_title"),
        func.paradedb.score(ItemVersion.id).label("score"),
    ).where(ItemVersion.is_head, _reaches(ItemVersion.id, "title", terms))
    bodies = _bodies(
        ItemVersion.item_id,
        literal(False),
        func.paradedb.score(Extraction.id),
    ).where(ItemVersion.is_head, _reaches(Extraction.id, "body", terms))
    return titles.union_all(bodies).subquery("hits")


def _ranked(terms: Sequence[Term]):
    """One row per item. A headline match outranks a reading; BM25 only breaks the tie."""
    hits = _hits(terms)
    return (
        select(
            hits.c.item_id.label("item_id"),
            func.bool_or(hits.c.in_title).label("in_title"),
            # Kept apart: a score from the title index and one from the body index are not
            # on one scale, so only a group's own score is allowed to order that group.
            func.max(case((hits.c.in_title, hits.c.score))).label("titled"),
            func.max(case((~hits.c.in_title, hits.c.score))).label("bodied"),
        )
        .group_by(hits.c.item_id)
        .subquery("ranked")
    )


def _wanted(terms: Sequence[Term]) -> tuple[str, ...]:
    """Every word the reader asked for, flattened: a phrase marks the same as its words."""
    return tuple({word.casefold() for term in terms for word in term.words})


def _marked(window: str, wanted: tuple[str, ...]) -> str:
    """What matched, wrapped. A prefix test, so the index's stemming is approximated."""
    out, at = [], 0
    for word in WORD.finditer(window):
        if not word.group().casefold().startswith(wanted):
            continue
        out += [window[at : word.start()], OPEN, word.group(), CLOSE]
        at = word.end()
    return "".join([*out, window[at:]])


def _boundary(flat: str, start: int, before: int) -> int:
    """The next word to start on, so the run-up does not open mid-word."""
    space = flat.find(" ", start) if start else -1
    return space + 1 if 0 <= space < before else start


def fragment(body: str, terms: Sequence[Term]) -> str:
    """A window of the reading around the first word that matched, with the words marked."""
    flat = extract.flatten(body)
    wanted = _wanted(terms)
    if not (flat and wanted):
        return ""

    first = next(
        (word for word in WORD.finditer(flat) if word.group().casefold().startswith(wanted)), None
    )
    # Nothing to point at. The index reaches text this does not — a term inside a bare URL,
    # which `flatten` drops — and an unmarked opening paragraph explains nothing.
    if first is None:
        return ""
    start = _boundary(flat, max(0, first.start() - LEAD_IN), first.start())
    window = extract.clipped(flat[start:], SNIPPET_CHARS)
    return ("…" if start else "") + _marked(window, wanted)


def _found(row: Mapping[str, Any], terms: Sequence[Term]) -> entries.Entry:
    """One row, with a fragment of its reading saying why the terms reached it."""
    fields: dict[str, Any] = dict(row)
    fields["snippet"] = fragment(fields.pop("body"), terms)
    return entries.Entry(**fields)


def _depth(after: str) -> int:
    """Search pages by depth: relevance is not a column, so there is no keyset to cut on."""
    if not after:
        return 0
    # `isascii` as well, or `isdigit` accepts '\u00b2' and int() then refuses it.
    if not (after.isascii() and after.isdigit()) or int(after) > MAX_DEPTH:
        raise BadQuery(after)
    return int(after)


def _total(matched: Select) -> Select:
    return select(func.count()).select_from(matched.subquery("matched"))


async def deep(
    session: AsyncSession,
    narrowed: Select,
    asked: Query,
    *,
    after: str = "",
    limit: int = entries.DEFAULT_LIMIT,
) -> Found:
    """A page of what the words reach, best first. `narrowed` carries every other filter."""
    depth, limit = _depth(after), entries.bounded(limit)
    wanted = asked.wanted
    ranked = _ranked(wanted)
    matched = narrowed.join(ranked, ranked.c.item_id == Item.id)

    rows = (
        await session.execute(
            matched.add_columns(Item.reading_body.label("body"))
            .order_by(
                ranked.c.in_title.desc(),
                # Whichever group the row is in, ordered by that group's own score.
                func.coalesce(ranked.c.titled, ranked.c.bodied).desc(),
                Item.first_seen_at.desc(),
                # A total order, or two rows tied on all three above can swap between
                # pages and one of them is served twice while the other is never served.
                Item.id.desc(),
            )
            .offset(depth)
            .limit(limit + 1)
        )
    ).mappings()
    found = tuple(_found(row, wanted) for row in rows.fetchall())
    deeper = len(found) > limit and depth + limit <= MAX_DEPTH
    return Found(
        listing=entries.Listing(
            entries=found[:limit],
            cursor=str(depth + limit) if deeper else "",
            updated=await session.scalar(entries.last_poll()),
        ),
        total=await session.scalar(_total(matched)) or 0,
    )
