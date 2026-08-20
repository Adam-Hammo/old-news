import logging
import uuid

from old_news import fetch, politeness, robots
from old_news.config import get_settings
from old_news.ingest import service
from old_news.observability import count
from old_news.tasks.app import app
from old_news.tasks.tracing import defer_unless_queued, task

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
    # Whatever these hosts asked for in robots.txt, honoured as a longer gap.
    crawl_delays = await robots.crawl_delays(poll.host for poll in polls)
    delays = politeness.stagger(
        (poll.host for poll in polls),
        minimum=settings.http.min_host_interval_seconds,
        crawl_delays=crawl_delays,
    )

    deferred = 0
    for poll, delay in zip(polls, delays, strict=True):
        deferred += await defer_unless_queued(
            poll_feed.configure(
                # One poll per feed in flight. A feed slower than its interval
                # would otherwise stack up behind itself forever.
                queueing_lock=f"feed:{poll.feed_id}",
                # Postgres hands out one job per host at a time, so nothing here keeps state.
                lock=politeness.host_lock(poll.host),
                schedule_in={"seconds": delay} if delay else None,
            ),
            feed_id=str(poll.feed_id),
        )

    if polls:
        logger.info("deferred %d of %d due feeds", deferred, len(polls))
        count("ingest.polls.deferred", deferred)
        count("ingest.polls.already_queued", len(polls) - deferred)
