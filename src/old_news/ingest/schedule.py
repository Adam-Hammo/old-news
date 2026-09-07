"""When to poll next. Pure functions; the failure half lives in `politeness.backoff`."""

import datetime

from old_news.config import IngestSettings
from old_news.politeness import backoff


def _bounds(settings: IngestSettings, ceiling: int) -> backoff.Policy:
    return backoff.Policy(
        minimum_seconds=settings.min_interval_seconds,
        maximum_seconds=ceiling,
        factor=settings.backoff_factor,
        max_failures=settings.max_consecutive_failures,
    )


def policy(settings: IngestSettings) -> backoff.Policy:
    """A healthy feed's bounds: how long a quiet one may go unseen."""
    return _bounds(settings, settings.max_interval_seconds)


def waiting_out(settings: IngestSettings) -> backoff.Policy:
    """A feed that is not answering: how long a publisher gets to be down."""
    return _bounds(settings, settings.max_backoff_seconds)


def clamp_interval(seconds: float, settings: IngestSettings) -> int:
    """A wait somebody else asked for, held inside the bounds we wait out a fault within."""
    return backoff.clamp(seconds, waiting_out(settings))


def next_interval(
    settings: IngestSettings,
    *,
    current_seconds: int | None = None,
    failures: int = 0,
    new_items: int = 0,
    ttl_seconds: int | None = None,
) -> int:
    """How long to wait before the next poll. A feed that published is visited sooner."""
    if failures > 0:
        clamped = backoff.interval(
            waiting_out(settings),
            failures=failures,
            base_seconds=settings.default_interval_seconds,
        )
    else:
        bounds = policy(settings)
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
