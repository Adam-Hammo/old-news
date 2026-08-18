import asyncio

from old_news.tasks.maintenance import heartbeat


async def test_worker_runs_a_job_against_real_postgres(no_jobs: None, queue_app):
    """`no_jobs` rather than `database`: this asserts a property of the whole queue,
    so a job left behind by any earlier test fails it."""
    async with queue_app.open_async():
        await heartbeat.defer_async(note="from-postgres")

        worker = asyncio.create_task(queue_app.run_worker_async(wait=False))
        await asyncio.wait_for(worker, timeout=30)

        status = await queue_app.job_manager.list_jobs_async()

    assert all(job.status == "succeeded" for job in status)
