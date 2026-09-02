"""Which reading wins, and whether the queries that decide it stayed correlated."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from old_news.db import Base, ExtractionSource, Feed, Host, Item, ItemVersion, item_reading
from old_news.db.models.item import READING_PREFERENCE


def test_every_source_is_ranked():
    """The guard the tie-break needs: a source added to the enum and not to the
    preference silently sorts last, and nothing about reading it would say so."""
    assert set(READING_PREFERENCE) == set(ExtractionSource)


def _sql(expression: Any, entity: type | None = None) -> str:
    """Compiled the way a real query would ask it: without `select_from` the expression has
    nothing to correlate against and the check below reads a false positive."""
    statement = select(expression)
    if entity is not None:
        statement = statement.select_from(entity)
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _naming(sql: str, table: str) -> list[str]:
    """FROM clauses that list `table` under its own name: aliased is a different reference,
    not a lost correlation, so only a bare entry counts."""
    clauses = [line.strip() for line in sql.splitlines() if line.strip().startswith("FROM ")]
    return [
        clause
        for clause in clauses
        if table in [entry.strip() for entry in clause.removeprefix("FROM ").split(",")]
    ]


def test_the_preference_reaches_the_sql():
    """A `CASE` over named sources, not `ORDER BY source`, which ranked them by spelling."""
    ranked = _sql(ItemVersion.reading_body, ItemVersion)
    ranked = ranked[ranked.index("ORDER BY") :]

    assert ranked.index("'feed'") < ranked.index("'page'")


def test_the_ordering_asks_its_questions_in_order():
    """Whole article, then enough to be one, then what was kept, then length. Reordered,
    a page of boilerplate beats a comic and a heading-stripped feed beats its own page."""
    ranked = _sql(ItemVersion.reading_body, ItemVersion)
    ranked = ranked[ranked.index("ORDER BY") :]

    # Each anchor is the tail of one key, so the window's own mention of `char_count`
    # cannot be mistaken for the key that follows it.
    keys = [
        ranked.index(key)
        for key in ("OVER ()) DESC", ">= 500 DESC", "structure_count DESC", "char_count DESC")
    ]
    assert keys == sorted(keys), ranked


def test_the_share_is_measured_against_the_readings_being_ranked():
    """An unpartitioned window over the subquery's own rows. Partitioned or hoisted, the
    comparison becomes "the longest thing in the archive" and every reading loses it."""
    ranked = _sql(ItemVersion.reading_body, ItemVersion)

    assert "max(extractions.char_count) OVER ()" in ranked


# Everything here answers a question about *one* row using a subquery over the same table
# the outer query selects from. Each one is a place a lost correlation reads as valid SQL
# and silently answers for the whole archive instead.
CORRELATED = [
    (ItemVersion, "reading_body"),
    (ItemVersion, "has_feed_text"),
    (ItemVersion, "is_head"),
    (Item, "reading_body"),
    (Item, "version_count"),
    (Host, "capture_failures"),
    (Host, "last_capture_failure"),
    (Feed, "consecutive_failures"),
    (Feed, "gone"),
]


@pytest.mark.parametrize(("entity", "attribute"), CORRELATED)
def test_a_correlated_subquery_does_not_re_list_its_outer_table(entity: type[Base], attribute: str):
    """One `FROM` naming the outer table — its own. A second turns "this row" into "any
    row" and compiles fine. Textual, because correlation is decided at compile time rather
    than stored: `get_final_froms()` reports the same thing either way."""
    table = entity.__tablename__
    naming = _naming(_sql(getattr(entity, attribute), entity), table)

    assert len(naming) == 1, (
        f"{entity.__name__}.{attribute} lost its correlation: {table} named in {naming}"
    )


def test_the_reading_of_an_item_survives_two_levels_of_nesting():
    """The only one of the family with a correlated subquery inside another."""
    naming = _naming(_sql(item_reading(ExtractionSource.FEED), Item), Item.__tablename__)

    assert len(naming) == 1, f"item_reading lost its correlation: items named in {naming}"
