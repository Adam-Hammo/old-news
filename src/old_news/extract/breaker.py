"""Whether a publisher is refusing us, rather than one article being unavailable."""

import datetime
import uuid

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import Host
from old_news.politeness import backoff


def refusing(host, settings: ExtractSettings, now: datetime.datetime) -> ColumnElement[bool]:
    """Whether this host is shut and its probe is not yet due.

    Goes false while a probe is due, so one capture gets through and the count it reads
    can move again — a breaker with no probe freezes its own input. Subtracting the
    threshold first starts the wait at the minimum instead of several doublings deep.
    """
    policy = backoff.policy_for(settings.host_probe)
    threshold = settings.host_failure_threshold
    return (host.capture_failures >= threshold) & (
        backoff.due_at(host.last_capture_failure, host.capture_failures - threshold, policy) > now
    )


@db.transactional
async def refusing_host(
    session: AsyncSession, host_id: uuid.UUID, settings: ExtractSettings
) -> bool:
    """The same predicate for one host, for the check in front of a fetch."""
    closed = await session.execute(
        select(refusing(Host, settings, datetime.datetime.now(datetime.UTC))).where(
            Host.id == host_id
        )
    )
    return bool(closed.scalar_one_or_none())
