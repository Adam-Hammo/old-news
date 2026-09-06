"""Keyword search over what is held. The one thing an archive this size cannot do by scrolling."""

import dataclasses
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, case, cast, func, literal, select
from sqlalchemy.dialects.postgresql import TEXT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from old_news import db, extract
from old_news.config import KindleSettings
from old_news.db import Extraction, Item, ItemVersion
from old_news.ui import entries

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


class BadQuery(ValueError):
    """Handed something that is not a search: no words in it, or a page that is not a number."""


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


def _matches(key: InstrumentedAttribute, field: str, terms: str):
    """Every word of it, and as words: not any-of-them, and not query syntax."""
    return key.op("@@@")(func.paradedb.match(_field(field), terms, *DEFAULTS, True))


def _hits(terms: str):
    """Every item the terms reach, by headline and by reading, as one set of ids."""
    # Head versions only: a liveblog rewrites its headline, and matching the one it
    # replaced surfaces an article whose headline says something else.
    titles = select(
        ItemVersion.item_id.label("item_id"),
        literal(True).label("in_title"),
        func.paradedb.score(ItemVersion.id).label("score"),
    ).where(ItemVersion.is_head, _matches(ItemVersion.id, "title", terms))
    bodies = (
        select(
            ItemVersion.item_id,
            literal(False),
            func.paradedb.score(Extraction.id),
        )
        .select_from(Extraction)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
        .where(ItemVersion.is_head, _matches(Extraction.id, "body", terms))
    )
    return titles.union_all(bodies).subquery("hits")


def _ranked(terms: str):
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


def _wanted(terms: str) -> tuple[str, ...]:
    return tuple({word.casefold() for word in WORD.findall(terms)})


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


def fragment(body: str, terms: str) -> str:
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


def _found(row: Mapping[str, Any], terms: str) -> entries.Entry:
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


@db.transactional
async def look(
    session: AsyncSession,
    settings: KindleSettings,
    *,
    terms: str,
    after: str = "",
    limit: int = entries.DEFAULT_LIMIT,
) -> Found:
    """What the terms reach, best first. Only the head version — the history is a different ask."""
    terms = terms.strip()
    if not terms:
        raise BadQuery("nothing to search for")

    depth, limit = _depth(after), entries.bounded(limit)
    ranked = _ranked(terms)
    matched = entries.listed(settings).join(ranked, ranked.c.item_id == Item.id)

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
    found = tuple(_found(row, terms) for row in rows.fetchall())
    deeper = len(found) > limit and depth + limit <= MAX_DEPTH
    return Found(
        listing=entries.Listing(
            entries=found[:limit],
            cursor=str(depth + limit) if deeper else "",
            updated=await session.scalar(entries.last_poll()),
            shelf=terms,
        ),
        total=await session.scalar(_total(matched)) or 0,
    )
