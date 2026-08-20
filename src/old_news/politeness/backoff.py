"""How long to wait before asking again. Pure functions over a policy.

Spelled twice, in Python and in SQL, because one caller decides in advance and another
needs it inside a `WHERE`. `test_backoff.py` asserts the two agree.
"""

import dataclasses

from sqlalchemy import ColumnElement, func
from sqlalchemy.sql.elements import ColumnClause

from old_news.config.retry import RetrySettings


@dataclasses.dataclass(frozen=True, slots=True)
class Policy:
    """The bounds one kind of retry moves within."""

    minimum_seconds: int
    maximum_seconds: int
    factor: float
    max_failures: int


def policy_for(settings: RetrySettings) -> Policy:
    """The configured bounds, in the shape the arithmetic wants."""
    return Policy(**settings.model_dump())


def clamp(seconds: float, policy: Policy) -> int:
    """Any wait, held inside the bounds. Public because `Retry-After` needs it too."""
    return int(min(max(seconds, policy.minimum_seconds), policy.maximum_seconds))


def interval(policy: Policy, *, failures: int, base_seconds: float | None = None) -> int:
    """Exponential in consecutive failures. `base_seconds` for callers with a cadence."""
    base = policy.minimum_seconds if base_seconds is None else base_seconds
    return clamp(base * policy.factor**failures, policy)


def due_at(
    last_attempt: ColumnClause | ColumnElement, failures: ColumnElement, policy: Policy
) -> ColumnElement:
    """The interval as SQL, so a batch can be ordered and limited by it.

    Filtering in Python after a `LIMIT` would silently shrink every batch.
    """
    seconds = func.least(
        func.greatest(
            policy.minimum_seconds * func.power(policy.factor, failures),
            policy.minimum_seconds,
        ),
        policy.maximum_seconds,
    )
    return last_attempt + func.make_interval(0, 0, 0, 0, 0, 0, seconds)
