import logging

from procrastinate import builtin_tasks
from procrastinate.job_context import JobContext

from old_news.config import get_settings
from old_news.db import dictionaries
from old_news.observability import count, gauge
from old_news.tasks.app import app
from old_news.tasks.tracing import task

logger = logging.getLogger(__name__)

# A worker that dies mid-job leaves the job stuck in `doing`. Nothing else notices.
STALLED_AFTER_SECONDS = 60.0

JOB_STATUSES = ("todo", "doing", "failed", "cancelled", "aborted")


@task(app, name="heartbeat")
async def heartbeat(note: str = "") -> str:
    """Proves the queue round-trips end to end. Delete once real tasks exist."""
    logger.info("heartbeat %s", note)
    return note


@app.periodic(cron="* * * * *", periodic_id="queue_metrics")
@app.task(name="queue_metrics")
async def queue_metrics(timestamp: int) -> None:
    """Queue depth and stalled workers, once a minute."""
    manager = app.job_manager

    for queue in await manager.list_queues_async():
        for status in JOB_STATUSES:
            gauge(f"queue.{status}", queue[status], unit="{job}", queue=queue["name"])

    stalled = list(await manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER_SECONDS))
    gauge("queue.stalled", len(stalled), unit="{job}")
    if stalled:
        logger.warning("%d stalled jobs: %s", len(stalled), [job.id for job in stalled])


@app.periodic(cron="0 4 * * *", periodic_id="prune_jobs")
@app.task(name="prune_jobs", pass_context=True)
async def prune_jobs(context: JobContext, timestamp: int) -> None:
    """Successful jobs are deleted on completion; this sweeps up what's left."""
    await builtin_tasks.remove_old_jobs(
        context,
        max_hours=24 * 7,
        remove_failed=True,
        remove_cancelled=True,
        remove_aborted=True,
    )


# Hourly, not nightly: an untrained scope stores at twice the size and is never rewritten.
# Once every scope has a fresh dictionary the sweep returns nothing, so asking is cheap.
@app.periodic(cron="17 * * * *", periodic_id="train_dictionaries")
@app.task(name="train_dictionaries")
async def train_dictionaries(timestamp: int) -> None:
    """Teach compression what a feed's documents and a publisher's pages look like.

    Nothing already written is rewritten: a body keeps pointing at whatever compressed it.
    """
    settings = get_settings().storage
    batch = settings.dictionary_batch_size

    for feed_id in await dictionaries.feeds_wanting_a_dictionary(settings, batch):
        samples = await dictionaries.feed_samples(feed_id, settings.dictionary_sample_limit)
        if (trained := dictionaries.train(samples, settings)) is not None:
            await dictionaries.store_for_feed(feed_id, trained)
            count("storage.dictionaries.trained", scope="feed")

    for host_id in await dictionaries.hosts_wanting_a_dictionary(settings, batch):
        samples = await dictionaries.host_samples(host_id, settings.dictionary_sample_limit)
        if (trained := dictionaries.train(samples, settings)) is not None:
            await dictionaries.store_for_host(host_id, trained)
            count("storage.dictionaries.trained", scope="host")
