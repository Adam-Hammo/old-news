"""How long to wait before asking again, after being told no.

Pure functions over a policy. Feeds, pages and images fail the same way and so back
off the same way; they differ only in the numbers, which is what `Policy` carries.

Two forms of the same arithmetic, because one caller decides in Python and another
needs it inside a `WHERE` clause. `test_backoff.py` asserts they agree.
"""

import dataclasses
import datetime

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
    """Any wait, held inside the bounds. Public because `Retry-After` needs the same
    clamping a computed interval does."""
    return int(min(max(seconds, policy.minimum_seconds), policy.maximum_seconds))


def interval(policy: Policy, *, failures: int, base_seconds: float | None = None) -> int:
    """Exponential in consecutive failures. `base_seconds` is for callers with a
    cadence of their own — a feed's current interval — rather than a flat floor."""
    base = policy.minimum_seconds if base_seconds is None else base_seconds
    return clamp(base * policy.factor**failures, policy)


def retry_at(
    now: datetime.datetime, policy: Policy, *, failures: int, base_seconds: float | None = None
) -> datetime.datetime:
    return now + datetime.timedelta(
        seconds=interval(policy, failures=failures, base_seconds=base_seconds)
    )


def exhausted(policy: Policy, *, failures: int) -> bool:
    """Whether to stop asking. What stopping means is the caller's business."""
    return failures >= policy.max_failures


def due_at(
    last_attempt: ColumnClause | ColumnElement, failures: ColumnElement, policy: Policy
) -> ColumnElement:
    """`retry_at` as SQL, for the sweeps that pick their own work.

    Postgres does the arithmetic so a batch can be ordered and limited by it, which
    filtering in Python after a `LIMIT` could not.
    """
    seconds = func.least(
        func.greatest(
            policy.minimum_seconds * func.power(policy.factor, failures),
            policy.minimum_seconds,
        ),
        policy.maximum_seconds,
    )
    return last_attempt + func.make_interval(0, 0, 0, 0, 0, 0, seconds)
