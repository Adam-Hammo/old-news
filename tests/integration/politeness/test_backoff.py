"""That the two spellings of the backoff formula agree, by asking Postgres."""

import datetime

import pytest
from sqlalchemy import DateTime, cast, literal, select

from old_news import db
from old_news.config import ExtractSettings, IngestSettings
from old_news.ingest.schedule import policy as ingest_policy
from old_news.politeness import backoff

WHEN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

# Every policy the application configures, so agreement is checked against the numbers
# that ship rather than only ones a test invented.
CONFIGURED = {
    "ingest": ingest_policy(IngestSettings()),
    "capture": backoff.policy_for(ExtractSettings().capture_retry),
    "host-probe": backoff.policy_for(ExtractSettings().host_probe),
}


@pytest.mark.parametrize("name", sorted(CONFIGURED))
@pytest.mark.parametrize("failures", range(9))
async def test_postgres_computes_the_same_next_attempt(database: None, name: str, failures: int):
    """`due_at` exists so a sweep can order and limit by a backoff, which filtering in
    Python after a LIMIT could not. Two copies of one formula drift in silence."""
    policy = CONFIGURED[name]
    expression = backoff.due_at(
        cast(literal(WHEN), DateTime(timezone=True)), literal(failures), policy
    )

    async with db.session() as session:
        from_sql = (await session.execute(select(expression))).scalar_one()

    assert from_sql == backoff.retry_at(WHEN, policy, failures=failures)
