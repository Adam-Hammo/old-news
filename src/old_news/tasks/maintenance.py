import logging

from procrastinate import builtin_tasks
from procrastinate.job_context import JobContext

from old_news.observability import gauge
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
    """Queue depth and stalled workers, once a minute.

    `todo` climbing means the poller is falling behind. `stalled` above zero means
    a worker died holding jobs. Those are the two ways this queue actually fails.
    """
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
