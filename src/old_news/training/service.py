"""What the reader has said it does not want.

This phase asks one question — is this item blocked — and asks it as a clause inside
the sweep that finds work, so a batch limit still means what it says. Which field a
dimension looks at is decided here rather than by the caller: that is the rule's
meaning, not the query's.
"""

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from old_news.db import Dimension, Item, ItemVersion, TrainingRule


def _contains(
    haystack: InstrumentedAttribute[str], needle: InstrumentedAttribute[str]
) -> ColumnElement[bool]:
    """Case-insensitive substring, via position rather than LIKE.

    LIKE would need the pattern escaped, and it cannot be: the pattern is a column, so
    there is nothing to escape client-side. `position` has no wildcards to begin with, so
    a rule containing `_` or `%` — and URLs are full of the former — means itself.
    """
    return func.strpos(func.lower(haystack), func.lower(needle)) > 0


def _matches(rule: type[TrainingRule], version: type[ItemVersion]) -> ColumnElement[bool]:
    """One dimension per branch, so adding one is a branch and a migration together."""
    return or_(
        and_(rule.dimension == Dimension.TITLE_PHRASE, _contains(version.title, rule.pattern)),
        and_(rule.dimension == Dimension.URL_PATTERN, _contains(version.url, rule.pattern)),
    )


def blocked(version: type[ItemVersion], item: type[Item]) -> ColumnElement[bool]:
    """True where a blocking rule matches this version.

    The item is needed for scope: a rule with no feed is global, and one with a feed
    applies only there.
    """
    return exists(
        select(TrainingRule.id).where(
            TrainingRule.blocks.is_(True),
            or_(TrainingRule.feed_id.is_(None), TrainingRule.feed_id == item.feed_id),
            _matches(TrainingRule, version),
        )
    )
