"""When to poll next. Pure functions — no database, no clock, no I/O."""

import datetime

from old_news.config import IngestSettings

# 410 means the publisher has said the feed is gone for good.
PERMANENTLY_GONE = 410


def clamp_interval(seconds: float, settings: IngestSettings) -> int:
    """Any wait, held inside the configured bounds. Public because `Retry-After`
    needs the same clamping as a computed interval does."""
    return int(min(max(seconds, settings.min_interval_seconds), settings.max_interval_seconds))


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
    if failures > 0:
        interval = settings.default_interval_seconds * settings.backoff_factor**failures
    else:
        base = current_seconds or settings.default_interval_seconds
        multiplier = (
            settings.busy_interval_multiplier if new_items else settings.idle_interval_multiplier
        )
        interval = base * multiplier

    clamped = clamp_interval(interval, settings)

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


def should_suspend(settings: IngestSettings, *, failures: int, status: int | None = None) -> bool:
    if status == PERMANENTLY_GONE:
        return True
    return failures >= settings.max_consecutive_failures
