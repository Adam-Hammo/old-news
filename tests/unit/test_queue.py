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
