import asyncio

from procrastinate import PsycopgConnector

from old_news.config import DatabaseSettings
from old_news.tasks import app
from old_news.tasks.maintenance import heartbeat


async def test_worker_runs_a_job_against_real_postgres(database: None, database_url: str):
    connector = PsycopgConnector(conninfo=DatabaseSettings(url=database_url).psycopg_url)

    with app.replace_connector(connector) as live_app:
        async with live_app.open_async():
            await heartbeat.defer_async(note="from-postgres")

            worker = asyncio.create_task(live_app.run_worker_async(wait=False))
            await asyncio.wait_for(worker, timeout=30)

            status = await live_app.job_manager.list_jobs_async()

    assert all(job.status == "succeeded" for job in status)
