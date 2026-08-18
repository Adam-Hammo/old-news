"""Keeping each host's robots.txt current.

The fetches take the same per-host lock as a poll, so asking for the rules queues
behind that host's other traffic rather than racing it.
"""

import logging

from old_news import fetch, politeness, robots
from old_news.config import get_settings
from old_news.ingest import service
from old_news.tasks.app import app
from old_news.tasks.ingest import QUEUE, SCHEDULER_PRIORITY
from old_news.tasks.tracing import defer_unless_queued, task

logger = logging.getLogger(__name__)


@task(app, name="refresh_robots", queue=QUEUE)
async def refresh_robots(host: str) -> None:
    """A host, not a URL — this one is safe to log, unlike a feed's own address."""
    await robots.refresh(host, fetch.client(), get_settings())


@app.periodic(cron="*/15 * * * *", periodic_id="schedule_robots")
@app.task(name="schedule_robots", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_robots(timestamp: int) -> None:
    settings = get_settings()
    hosts = await service.subscribed_hosts()
    stale = await robots.stale_hosts(hosts, settings.robots.refresh_batch_size)

    for host in stale:
        await defer_unless_queued(
            refresh_robots.configure(
                # One refresh per host in flight, and behind that host's other work.
                queueing_lock=f"robots:{host}",
                lock=politeness.host_lock(host),
            ),
            host=host,
        )

    if stale:
        logger.info("refreshing robots.txt for %d hosts", len(stale))
