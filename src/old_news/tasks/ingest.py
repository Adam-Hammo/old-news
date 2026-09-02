import logging
import uuid

from old_news import fetch
from old_news.config import get_settings
from old_news.ingest import service
from old_news.observability import count
from old_news.tasks import sweep
from old_news.tasks.app import app
from old_news.tasks.tracing import task

logger = logging.getLogger(__name__)

QUEUE = "ingest"

# Without this the scheduler queues behind its own output, and a backlog is terminal.
SCHEDULER_PRIORITY = 10


@task(app, name="poll_feed", queue=QUEUE)
async def poll_feed(feed_id: str) -> None:
    """Takes an identifier, never a URL: procrastinate logs kwargs at INFO."""
    await service.poll_feed(uuid.UUID(feed_id), fetch.client(), get_settings())


@app.periodic(cron="* * * * *", periodic_id="schedule_polls")
@app.task(name="schedule_polls", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_polls(timestamp: int) -> None:
    settings = get_settings()
    polls = await service.due_polls(settings.ingest, settings.ingest.poll_batch_size)
    deferred = await sweep.defer_each(
        poll_feed,
        [poll.feed_id for poll in polls],
        kwarg="feed_id",
        lock_prefix="feed",
        hosts=[poll.host for poll in polls],
        min_host_interval_seconds=settings.http.min_host_interval_seconds,
    )

    if polls:
        logger.info("deferred %d of %d due feeds", deferred, len(polls))
        count("ingest.polls.deferred", deferred)
        count("ingest.polls.already_queued", len(polls) - deferred)
