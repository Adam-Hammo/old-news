import logging
import uuid

from old_news.config import get_settings
from old_news.fetch import Fetcher
from old_news.ingest import service
from old_news.tasks.app import app
from old_news.tasks.tracing import defer, task

logger = logging.getLogger(__name__)

QUEUE = "ingest"

# The scheduler runs every minute and is cheap; the polls it defers are neither.
# Without a higher priority it queues behind its own output, and a backlog stops
# anything ever being scheduled again.
SCHEDULER_PRIORITY = 10


@task(app, name="poll_feed", queue=QUEUE)
async def poll_feed(feed_id: str) -> None:
    """Takes an identifier, never a URL: procrastinate logs kwargs at INFO and a
    feed URL can carry an API key."""
    settings = get_settings()
    fetcher = Fetcher(settings.http)
    try:
        await service.poll_feed(uuid.UUID(feed_id), fetcher, settings)
    finally:
        await fetcher.aclose()


@app.periodic(cron="* * * * *", periodic_id="schedule_polls")
@app.task(name="schedule_polls", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_polls(timestamp: int) -> None:
    settings = get_settings()
    feed_ids = await service.due_feed_ids(settings.ingest.poll_batch_size)

    for feed_id in feed_ids:
        # One poll per feed in flight. A feed slower than its interval would
        # otherwise stack up behind itself forever.
        await defer(
            poll_feed.configure(queueing_lock=f"feed:{feed_id}"),
            feed_id=str(feed_id),
        )

    if feed_ids:
        logger.info("deferred %d feed polls", len(feed_ids))
