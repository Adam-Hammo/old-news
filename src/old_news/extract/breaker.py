"""Whether a publisher is refusing us, rather than one article being unavailable.

Per-version backoff leaves as many clocks as there are articles, all still knocking.
This is the one clock. Derived from the capture rows, which is why it needs the probe:
a breaker that stops attempts freezes the window it reads.

Counted per capture policy, like the per-version backoff. A host that refused the old way
of asking has not refused the new one, so a bump earns every publisher a fresh trial.
"""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import CAPTURE_POLICY, Host, PageCapture
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


def _closed(failures: int, latest: datetime.datetime | None, settings: ExtractSettings) -> bool:
    """Whether the run of refusals is long enough, and recent enough, to stop asking."""
    if latest is None or failures < settings.host_failure_threshold:
        return False
    policy = backoff.policy_for(settings.host_probe)
    # From the threshold, so the first wait is the minimum rather than several
    # doublings deep.
    probe_due = backoff.retry_at(
        latest, policy, failures=failures - settings.host_failure_threshold
    )
    return datetime.datetime.now(datetime.UTC) < probe_due


async def _recent_by_host(
    session: AsyncSession,
) -> dict[str, list[tuple[int, datetime.datetime]]]:
    """The last `WINDOW` captures for every host at once, newest first."""
    ranked = (
        select(
            Host.name.label("host"),
            PageCapture.status.label("status"),
            PageCapture.fetched_at.label("fetched_at"),
            func.row_number()
            .over(
                partition_by=PageCapture.host_id,
                order_by=PageCapture.fetched_at.desc(),
            )
            .label("rank"),
        )
        .join(Host, Host.id == PageCapture.host_id)
        .where(PageCapture.capture_policy == CAPTURE_POLICY)
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.host, ranked.c.status, ranked.c.fetched_at)
        .where(ranked.c.rank <= WINDOW)
        .order_by(ranked.c.host, ranked.c.fetched_at.desc())
    )

    recent: dict[str, list[tuple[int, datetime.datetime]]] = {}
    for host, status, fetched_at in rows:
        recent.setdefault(host, []).append((status, fetched_at))
    return recent


async def refusing_hosts(session: AsyncSession, settings: ExtractSettings) -> set[str]:
    """Every host currently not worth asking, in one query."""
    return {
        host
        for host, recent in (await _recent_by_host(session)).items()
        if _closed(*consecutive_failures(recent), settings)
    }


async def _recent(session: AsyncSession, host_id: uuid.UUID) -> list[tuple[int, datetime.datetime]]:
    rows = await session.execute(
        select(PageCapture.status, PageCapture.fetched_at)
        .where(
            PageCapture.host_id == host_id,
            PageCapture.capture_policy == CAPTURE_POLICY,
        )
        .order_by(PageCapture.fetched_at.desc())
        .limit(WINDOW)
    )
    return [(status, fetched_at) for status, fetched_at in rows.all()]


@db.transactional
async def refusing(session: AsyncSession, host_id: uuid.UUID, settings: ExtractSettings) -> bool:
    """Whether to skip this fetch. False while a probe is due, so one gets through."""
    return _closed(*consecutive_failures(await _recent(session, host_id)), settings)
