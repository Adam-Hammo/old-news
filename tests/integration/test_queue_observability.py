from litestar.testing import AsyncTestClient

from old_news.tasks.maintenance import heartbeat, queue_metrics
from old_news.tasks.tracing import TRACE_KEY, defer


async def test_queue_health_reports_depth_and_stalled(client: AsyncTestClient):
    response = await client.get("/health/queue")

    assert response.status_code == 200
    assert set(response.json()) >= {"todo", "doing", "failed", "stalled"}
    assert response.json()["stalled"] == 0


async def test_deferred_jobs_carry_trace_context(database: None, queue_app):
    async with queue_app.open_async():
        await defer(heartbeat, note="traced")
        jobs = list(await queue_app.job_manager.list_jobs_async(task="heartbeat"))

    assert any(TRACE_KEY in job.task_kwargs for job in jobs)


async def test_metrics_task_runs_against_a_real_queue(database: None, queue_app):
    """It reads list_queues_async and get_stalled_jobs; both must accept our arguments."""
    async with queue_app.open_async():
        await queue_metrics.func(timestamp=0)


def test_successful_jobs_are_deleted(queue_app):
    """delete_jobs=successful keeps the queue table from growing without bound."""
    assert queue_app.worker_defaults["delete_jobs"] == "successful"
