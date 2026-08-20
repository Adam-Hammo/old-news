"""Whether a publisher is refusing us, rather than one article being unavailable.

Per-version backoff leaves as many clocks as there are articles, all still knocking.
This is the one clock. Derived from the capture rows, which is why it needs the probe:
a breaker that stops attempts freezes the window it reads.
"""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import PageCapture
from old_news.politeness import backoff

# Undercounting only shortens the probe interval, so there is nothing to gain from more.
WINDOW = 50

# About a URL, not a publisher: a few dead links must not close a healthy host.
PER_URL_STATUS = frozenset({404, 410})


def _succeeded(status: int) -> bool:
    return 200 <= status < 300


def consecutive_failures(
    recent: list[tuple[int, datetime.datetime]],
) -> tuple[int, datetime.datetime | None]:
    """Host-scoped failures since the last success, newest first, and when.

    A per-URL status is stepped over: it is neither a failure nor a success here.
    """
    failures = 0
    latest = None
    for status, fetched_at in recent:
        if _succeeded(status):
            break
        if status in PER_URL_STATUS:
            continue
        if latest is None:
            latest = fetched_at
        failures += 1
    return failures, latest


@db.transactional
async def _recent(session: AsyncSession, host_id: uuid.UUID) -> list[tuple[int, datetime.datetime]]:
    rows = await session.execute(
        select(PageCapture.status, PageCapture.fetched_at)
        .where(PageCapture.host_id == host_id)
        .order_by(PageCapture.fetched_at.desc())
        .limit(WINDOW)
    )
    return [(status, fetched_at) for status, fetched_at in rows.all()]


async def refusing(host_id: uuid.UUID, settings: ExtractSettings) -> bool:
    """Whether to skip this fetch. False while a probe is due, so one gets through."""
    failures, latest = consecutive_failures(await _recent(host_id))
    if latest is None or failures < settings.host_failure_threshold:
        return False

    policy = backoff.policy_for(settings.host_probe)
    # From the threshold, so the first wait is the minimum rather than several
    # doublings deep.
    probe_due = backoff.retry_at(
        latest, policy, failures=failures - settings.host_failure_threshold
    )
    return datetime.datetime.now(datetime.UTC) < probe_due
