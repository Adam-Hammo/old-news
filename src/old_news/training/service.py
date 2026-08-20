"""What the reader has said it does not want, as a clause a sweep can put in its WHERE."""

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from old_news.db import Dimension, Item, ItemVersion, TrainingRule


def _contains(
    haystack: InstrumentedAttribute[str], needle: InstrumentedAttribute[str]
) -> ColumnElement[bool]:
    """Case-insensitive substring, via position rather than LIKE.

    The pattern is a column, so it cannot be escaped client-side. `strpos` has no
    wildcards, so a rule containing `_` or `%` means itself.
    """
    return func.strpos(func.lower(haystack), func.lower(needle)) > 0


def _matches(rule: type[TrainingRule], version: type[ItemVersion]) -> ColumnElement[bool]:
    """One dimension per branch, so adding one is a branch and a migration together."""
    return or_(
        and_(rule.dimension == Dimension.TITLE_PHRASE, _contains(version.title, rule.pattern)),
        and_(rule.dimension == Dimension.URL_PATTERN, _contains(version.url, rule.pattern)),
    )


def blocked(version: type[ItemVersion], item: type[Item]) -> ColumnElement[bool]:
    """True where a blocking rule matches this version. A rule with no feed is global."""
    return exists(
        select(TrainingRule.id).where(
            TrainingRule.blocks.is_(True),
            or_(TrainingRule.feed_id.is_(None), TrainingRule.feed_id == item.feed_id),
            _matches(TrainingRule, version),
        )
    )
