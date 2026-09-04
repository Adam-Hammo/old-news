"""Keyword search over what is held. The one thing an archive this size cannot do by scrolling."""

import dataclasses
import html
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, cast, func, literal, select
from sqlalchemy.dialects.postgresql import TEXT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from old_news import db, extract
from old_news.config import KindleSettings
from old_news.db import Extraction, Item, ItemVersion
from old_news.ui import entries

# Around what matched, and not spelt in markup: the fragment is markdown and gets
# flattened to prose, which would take any punctuation marker with it. The client splits
# on these to set what matched in bold.
OPEN = "\x02"
CLOSE = "\x03"

# Enough of the sentence to recognise the article by. The reader has the headline already.
SNIPPET_CHARS = 220


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
    titles = select(
        ItemVersion.item_id.label("item_id"),
        literal(True).label("in_title"),
        func.paradedb.score(ItemVersion.id).label("score"),
        cast(literal(""), TEXT).label("snippet"),
    ).where(_matches(ItemVersion.id, "title", terms))
    bodies = (
        select(
            ItemVersion.item_id,
            literal(False),
            func.paradedb.score(Extraction.id),
            func.paradedb.snippet(Extraction.body, OPEN, CLOSE, SNIPPET_CHARS),
        )
        .select_from(Extraction)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
        .where(_matches(Extraction.id, "body", terms))
    )
    return titles.union_all(bodies).subquery("hits")


def _ranked(terms: str):
    """One row per item. A headline match outranks a reading; BM25 only breaks the tie."""
    hits = _hits(terms)
    return (
        select(
            hits.c.item_id.label("item_id"),
            func.bool_or(hits.c.in_title).label("in_title"),
            func.max(hits.c.score).label("score"),
            # Any of them will do: they are fragments of the same article, and which
            # reading of it a phrase fell in is not something a reader is asking.
            func.max(hits.c.snippet).label("snippet"),
        )
        .group_by(hits.c.item_id)
        .subquery("ranked")
    )


def _found(row: Mapping[str, Any]) -> entries.Entry:
    """One row, with its fragment turned from the markdown that is stored into prose."""
    fields: dict[str, Any] = dict(row)
    # Two layers of entities, undone one at a time by whoever added one. `paradedb.snippet`
    # escapes what it returns for HTML; `flatten` then takes the reading's own.
    fragment = html.unescape(fields["snippet"])
    fields["snippet"] = extract.clipped(extract.flatten(fragment), SNIPPET_CHARS)
    return entries.Entry(**fields)


def _depth(after: str) -> int:
    """Search pages by depth: relevance is not a column, so there is no keyset to cut on."""
    if not after:
        return 0
    if not after.isdigit():
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
    matched = (
        entries.listed(settings)
        .add_columns(ranked.c.snippet.label("snippet"))
        .join(ranked, ranked.c.item_id == Item.id)
    )

    rows = (
        await session.execute(
            matched.order_by(
                ranked.c.in_title.desc(), ranked.c.score.desc(), Item.first_seen_at.desc()
            )
            .offset(depth)
            .limit(limit + 1)
        )
    ).mappings()
    found = tuple(_found(row) for row in rows.fetchall())
    return Found(
        listing=entries.Listing(
            entries=found[:limit],
            cursor=str(depth + limit) if len(found) > limit else "",
            updated=await session.scalar(entries.last_poll()),
            shelf=terms,
        ),
        total=await session.scalar(_total(matched)) or 0,
    )
