from procrastinate.testing import InMemoryConnector

from old_news.tasks import app
from old_news.tasks.maintenance import heartbeat


async def test_deferring_records_a_job():
    connector = InMemoryConnector()

    with app.replace_connector(connector):
        await heartbeat.defer_async(note="ping")

        jobs = connector.jobs
        assert len(jobs) == 1
        assert jobs[1]["task_name"] == "heartbeat"
        assert jobs[1]["args"] == {"note": "ping"}


def test_every_queue_a_task_declares_is_served():
    """A queue missing from `WorkerSettings` is a queue no worker listens to, and its jobs
    sit at `todo` forever. `default` holds the heartbeat and the nightly maintenance, so
    the failure is quiet and total."""
    import old_news.tasks.extract
    import old_news.tasks.ingest
    import old_news.tasks.maintenance
    import old_news.tasks.robots  # noqa: F401
    from old_news.config import WorkerSettings
    from old_news.tasks.app import app

    declared = {task.queue for task in app.tasks.values()}

    assert declared <= set(WorkerSettings().concurrency)
