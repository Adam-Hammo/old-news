"""One worker per queue, which is the shape the deployment runs."""

import asyncio
import time

from sqlalchemy import text

from old_news import db
from old_news.__main__ import _run_workers
from old_news.config import WorkerSettings
from old_news.tasks import extract as extract_tasks
from old_news.tasks import ingest as ingest_tasks
from old_news.tasks.app import app

DEFERRED = ("schedule_polls", "schedule_lead_images")


async def _drained(seconds: float) -> set[str]:
    """Poll until nothing this test deferred is left, and report what is if time runs out.

    A wall-clock deadline rather than a fixed count of sleeps, because each check costs a
    round trip and the count drifts with load. And it returns the leftover rather than a
    bool so a failure says whether a job is stuck or the box was just slow — the flake it
    replaces asserted `== set()` and told you nothing about which.
    """
    deadline = time.monotonic() + seconds
    # Polled: the state is a row in Postgres, so there is no event to wait on.
    while (outstanding := await _outstanding()) and time.monotonic() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.05)
    return outstanding


@db.transactional
async def _outstanding(session) -> set[str]:
    """Successful jobs are deleted on completion, so a name still present has not run.
    Scoped to what this test deferred: periodics fire during the run too."""
    rows = await session.execute(
        text("select task_name from procrastinate_jobs where task_name = any(:names)"),
        {"names": list(DEFERRED)},
    )
    return {name for (name,) in rows.all()}


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
        await app.configure_task(name="schedule_polls", queue="ingest").defer_async(timestamp=0)
        await app.configure_task(name="schedule_lead_images", queue="pages").defer_async(
            timestamp=0
        )

        assert await _outstanding() == set(DEFERRED)

        running = asyncio.create_task(_run_workers(queue_app, configured, stopping))
        leftover = await _drained(seconds=30)
        stopping.set()
        await asyncio.wait_for(running, timeout=10)

    assert leftover == set(), f"still queued after 30s: {sorted(leftover)}"


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

        await asyncio.wait_for(running, timeout=10)

    assert running.done() and not running.cancelled()
