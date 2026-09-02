from procrastinate.testing import InMemoryConnector

from old_news.config import WorkerSettings
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
    """A queue no worker listens to leaves its jobs at `todo` forever, quietly."""
    app.perform_import_paths()

    declared = {task.queue for task in app.tasks.values()}

    assert declared <= set(WorkerSettings().concurrency)
