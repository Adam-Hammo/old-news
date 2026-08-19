"""Whether a publisher is refusing us, rather than one article being unavailable.

A 403 on a page is a fact about that page. Every page on a host 403ing is a fact about
the publisher, and per-version backoff leaves as many independent clocks as there are
articles — all of them still knocking. This is the one clock.

Derived from the capture rows rather than stored, like the per-version backoff. The
trap that comes with deriving it: a breaker that stops attempts freezes the window it
reads, so it would never reopen. Hence the probe.
"""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import PageCapture
from old_news.politeness import backoff

# Enough rows to count a run of failures past any sane threshold. Undercounting only
# shortens the probe interval, so there is nothing to gain from reading more.
WINDOW = 50

# 404 and 410 are about a URL, not a publisher. Counting them would let a handful of
# dead links close a host that is answering everything else perfectly well.
PER_URL_STATUS = frozenset({404, 410})


def _succeeded(status: int) -> bool:
    return 200 <= status < 300


def consecutive_failures(
    recent: list[tuple[int, datetime.datetime]],
) -> tuple[int, datetime.datetime | None]:
    """How many host-scoped failures since the last success, and when the newest was.

    `recent` is newest first. A per-URL status is stepped over rather than counted or
    treated as a success — it says nothing either way.
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
    """Whether to skip this fetch because the host is not answering anyone.

    False while a probe is due, so one request per interval goes out to find out
    whether that is still true.
    """
    failures, latest = consecutive_failures(await _recent(host_id))
    if latest is None or failures < settings.host_failure_threshold:
        return False

    policy = backoff.policy_for(settings.host_probe)
    # Counted from the threshold, so the first wait after tripping is the minimum
    # rather than one already several doublings deep.
    probe_due = backoff.retry_at(
        latest, policy, failures=failures - settings.host_failure_threshold
    )
    return datetime.datetime.now(datetime.UTC) < probe_due
