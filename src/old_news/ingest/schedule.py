"""When to poll next. Pure functions — no database, no clock, no I/O.

Cadence is this module's; the failure half is `politeness.backoff`, shared with the
capture sweeps because a feed and a page are refused in the same ways.
"""

import datetime

from old_news.config import IngestSettings
from old_news.politeness import backoff


def policy(settings: IngestSettings) -> backoff.Policy:
    """A feed's retry bounds, in the shared shape."""
    return backoff.Policy(
        minimum_seconds=settings.min_interval_seconds,
        maximum_seconds=settings.max_interval_seconds,
        factor=settings.backoff_factor,
        max_failures=settings.max_consecutive_failures,
    )


def clamp_interval(seconds: float, settings: IngestSettings) -> int:
    """Any wait, held inside the configured bounds. Public because `Retry-After`
    needs the same clamping as a computed interval does."""
    return backoff.clamp(seconds, policy(settings))


def next_interval(
    settings: IngestSettings,
    *,
    current_seconds: int | None = None,
    failures: int = 0,
    new_items: int = 0,
    ttl_seconds: int | None = None,
) -> int:
    """How long to wait before the next poll.

    Failures back off exponentially. A feed that published gets visited sooner,
    one that didn't drifts later, so a quiet feed costs less over time.
    """
    bounds = policy(settings)
    if failures > 0:
        clamped = backoff.interval(
            bounds, failures=failures, base_seconds=settings.default_interval_seconds
        )
    else:
        base = current_seconds or settings.default_interval_seconds
        multiplier = (
            settings.busy_interval_multiplier if new_items else settings.idle_interval_multiplier
        )
        clamped = backoff.clamp(base * multiplier, bounds)

    # <ttl> is a request to poll *less* often, so it raises the floor and is
    # allowed to push past our own ceiling. Ignoring it is how you get blocked.
    if settings.honour_feed_ttl and ttl_seconds:
        return max(clamped, ttl_seconds)
    return clamped


def next_poll_at(
    now: datetime.datetime,
    settings: IngestSettings,
    *,
    current_seconds: int | None = None,
    failures: int = 0,
    new_items: int = 0,
    ttl_seconds: int | None = None,
) -> datetime.datetime:
    seconds = next_interval(
        settings,
        current_seconds=current_seconds,
        failures=failures,
        new_items=new_items,
        ttl_seconds=ttl_seconds,
    )
    return now + datetime.timedelta(seconds=seconds)
