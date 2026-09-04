"""Building the periodical, on its own queue because a conversion holds a worker for minutes."""

import logging

from old_news import kindle
from old_news.config import get_settings
from old_news.observability import count
from old_news.tasks.app import app
from old_news.tasks.tracing import defer_unless_queued, task

logger = logging.getLogger(__name__)

QUEUE = "kindle"


@task(app, name="build_issue", queue=QUEUE)
async def build_issue() -> None:
    """A quiet week builds nothing, which is not a failure."""
    built = await kindle.build_issue(get_settings().kindle)
    if built.issue_id is None:
        return
    logger.info(
        "issue %s: %d articles, %d bytes, sent=%s %s",
        built.issue_id,
        built.articles,
        built.byte_size,
        built.sent,
        built.error,
    )


@app.periodic(cron=get_settings().kindle.cron, periodic_id="schedule_issue")
@app.task(name="schedule_issue", queue=QUEUE)
async def schedule_issue(timestamp: int) -> None:
    """Defers rather than builds, so a slow conversion cannot delay the next cron tick."""
    settings = get_settings().kindle
    if not settings.enabled:
        return
    # Queueing lock, or a conversion that overran gets a second one on top of it.
    if await defer_unless_queued(build_issue.configure(queueing_lock="kindle:issue")):
        count("kindle.issues.deferred")
