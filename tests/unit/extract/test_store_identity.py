"""The upsert key and the constraint it names have to be the same columns."""

from old_news.db import Extraction
from old_news.extract.service import _IDENTITY, _UNIQUE


def test_the_upsert_never_rewrites_the_columns_it_matched_on():
    """`store` upserts on this constraint and excludes `_IDENTITY` from the SET clause.
    Let the two drift and the write moves the row it just found instead of updating it —
    silently, and only for the second reading of any version."""
    table = Extraction.metadata.tables["extractions"]
    constraint = next(c for c in table.constraints if c.name == _UNIQUE)

    assert {column.name for column in constraint.columns} == set(_IDENTITY)
