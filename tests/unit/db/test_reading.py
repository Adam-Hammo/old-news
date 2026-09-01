"""Which reading wins, and whether the queries that decide it stayed correlated."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from old_news.db import ExtractionSource, Feed, Host, Item, ItemVersion
from old_news.db.models.item import READING_PREFERENCE


def test_every_source_is_ranked():
    """The guard the tie-break needs: a source added to the enum and not to the
    preference silently sorts last, and nothing about reading it would say so."""
    assert set(READING_PREFERENCE) == set(ExtractionSource)


def _sql(expression: Any, entity: type | None = None) -> str:
    """Compiled the way a real query would ask it: the entity anchors the outer FROM.

    Without `select_from` a bare expression has nothing to correlate against, so a nested
    select names the outer table legitimately and the check below reads a false positive.
    """
    statement = select(expression)
    if entity is not None:
        statement = statement.select_from(entity)
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _naming(sql: str, table: str) -> list[str]:
    """FROM clauses that list `table` under its own name.

    Aliased is a different reference — `is_head` self-joins `item_versions AS successor`
    and that is not a lost correlation — so only a bare entry counts.
    """
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
    ("ItemVersion.reading_body", ItemVersion, ItemVersion.reading_body, "item_versions"),
    ("ItemVersion.has_feed_text", ItemVersion, ItemVersion.has_feed_text, "item_versions"),
    ("ItemVersion.is_head", ItemVersion, ItemVersion.is_head, "item_versions"),
    ("Item.reading_body", Item, Item.reading_body, "items"),
    ("Item.version_count", Item, Item.version_count, "items"),
    ("Host.capture_failures", Host, Host.capture_failures, "hosts"),
    ("Host.last_capture_failure", Host, Host.last_capture_failure, "hosts"),
    ("Feed.consecutive_failures", Feed, Feed.consecutive_failures, "feeds"),
    ("Feed.gone", Feed, Feed.gone, "feeds"),
]


@pytest.mark.parametrize(("name", "entity", "expression", "table"), CORRELATED)
def test_a_correlated_subquery_does_not_re_list_its_outer_table(
    name: str, entity: type, expression: Any, table: str
):
    """One `FROM` naming the outer table — its own. A second means a nested select put it
    back in its own `FROM`, which turns "this row" into "any row" and compiles fine.

    Textual, because correlation is decided when the statement is compiled rather than
    stored on the subquery: `get_final_froms()` reports the same thing either way.
    """
    naming = _naming(_sql(expression, entity), table)

    assert len(naming) == 1, f"{name} lost its correlation: {table} named in {naming}"
