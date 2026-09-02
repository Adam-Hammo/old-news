"""One worker per queue, which is the shape the deployment runs."""

import asyncio
import contextlib
import time

from sqlalchemy import text

from old_news import db
from old_news.__main__ import _run_workers
from old_news.config import WorkerSettings
from old_news.tasks import extract as extract_tasks
from old_news.tasks import ingest as ingest_tasks
from old_news.tasks.app import app

DRAIN_SECONDS = 30

# Procrastinate shields its own run loop, so a cancelled worker winds down gracefully
# rather than promptly: it drains in-flight jobs and its 5s and 10s pollers see the stop
# only between sleeps. Bounded generously, and asserted by one test rather than every one.
SHUTDOWN_SECONDS = 60


async def _drained(ids: set[int], seconds: float) -> set[int]:
    """Poll until none of `ids` is left, returning whatever still is if time runs out."""
    deadline = time.monotonic() + seconds
    # Polled: the state is a row in Postgres, so there is no event to wait on.
    while (left := await _outstanding(ids)) and time.monotonic() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.05)
    return left


@db.transactional
async def _outstanding(session, ids: set[int]) -> set[int]:
    """Successful jobs are deleted on completion, so an id still present has not run."""
    rows = await session.execute(
        text("select id from procrastinate_jobs where id = any(:ids)"), {"ids": list(ids)}
    )
    return {job_id for (job_id,) in rows.all()}


async def test_a_worker_per_queue_runs_jobs_on_both(
    no_jobs: None, queue_app, settings, monkeypatch
):
    """A flood on one queue must not occupy the slots the other needs, which needs a pool
    each. The failure this guards is the queues existing in name only."""
    monkeypatch.setattr(ingest_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(extract_tasks, "get_settings", lambda: settings)
    configured = settings.model_copy(
        update={"worker": WorkerSettings(concurrency={"ingest": 1, "pages": 1})}
    )
    stopping = asyncio.Event()

    async with queue_app.open_async():
        # By id, not name: both tasks are also periodic, so one firing mid-drain would
        # look like the job this test deferred never having run.
        deferred = {
            await app.configure_task(name="schedule_polls", queue="ingest").defer_async(
                timestamp=0
            ),
            await app.configure_task(name="schedule_lead_images", queue="pages").defer_async(
                timestamp=0
            ),
        }
        assert await _outstanding(deferred) == deferred

        running = asyncio.create_task(_run_workers(queue_app, configured, stopping))
        try:
            leftover = await _drained(deferred, seconds=DRAIN_SECONDS)
            assert leftover == set(), f"still queued after {DRAIN_SECONDS}s: {sorted(leftover)}"
        finally:
            # Winding down is the next test's subject, so a slow one must not fail this.
            stopping.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(running, timeout=SHUTDOWN_SECONDS)


async def test_setting_the_event_shuts_every_worker_down(no_jobs: None, queue_app, settings):
    """Signals are handled once for the process, so this is what SIGTERM reaches. If a
    worker ignored it the container would run until Docker lost patience."""
    configured = settings.model_copy(
        update={"worker": WorkerSettings(concurrency={"ingest": 1, "pages": 1})}
    )
    stopping = asyncio.Event()

    async with queue_app.open_async():
        running = asyncio.create_task(_run_workers(queue_app, configured, stopping))
        await asyncio.sleep(0.2)
        stopping.set()

        await asyncio.wait_for(running, timeout=SHUTDOWN_SECONDS)

    assert running.done() and not running.cancelled()
