"""SQLAlchemy instrumentation is forced past its own version check, twice over.

`opentelemetry-instrumentation-sqlalchemy` pins SQLAlchemy < 2.1, and this project
needs 2.1 for free-threaded Python, so `instrument_engine` passes `skip_dep_check`.
An instrumentor that refuses a dependency does not raise — it logs and returns, and
every query goes untraced from then on.

The second trap is ordering: instrumenting with no argument patches sqlalchemy's
factory functions, but `db.session` binds `create_async_engine` at import, so the
patched name is never the one it calls. Handing the engine over is what fixes it,
and `test_session_hands_its_engine_over` is what keeps it handed over.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import logfire
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from old_news import observability
from old_news.config import Settings
from old_news.observability import telemetry

MISSING_TABLE = "SELECT * FROM table_that_does_not_exist"
SESSION_MODULE = Path(telemetry.__file__).resolve().parents[2] / "old_news" / "db" / "session.py"


@pytest.fixture(scope="session")
def exporter() -> Iterator[TestExporter]:
    """Configured once: a second logfire provider would leave the first one's spans
    going somewhere this test cannot see."""
    collected = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(collected)],
    )
    yield collected


@pytest.fixture(scope="session")
async def engine(
    exporter: TestExporter, settings: Settings, migrated: None
) -> AsyncIterator[AsyncEngine]:
    """One engine for the session, because the instrumentor is a singleton: a second
    `instrument()` warns and returns, leaving the second engine untraced. Each process
    configures one engine, so that costs production nothing."""
    telemetry._instrument_database = True  # what observability.configure() sets
    current = create_async_engine(settings.database.sqlalchemy_url)
    observability.instrument_engine(current)
    yield current
    await current.dispose()
    telemetry._instrument_database = False


@pytest.fixture(autouse=True)
def _clear(exporter: TestExporter) -> None:
    exporter.exported_spans.clear()


def _statements(exporter: TestExporter) -> dict[str, ReadableSpan]:
    return {
        str((span.attributes or {}).get("db.statement")): span
        for span in exporter.exported_spans
        if (span.attributes or {}).get("db.statement")
    }


async def test_a_query_is_traced_with_its_statement(engine: AsyncEngine, exporter: TestExporter):
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    assert "SELECT 1" in _statements(exporter)


async def test_a_failing_statement_is_traced_as_an_error(
    engine: AsyncEngine, exporter: TestExporter
):
    """The reason SQLAlchemy is instrumented and asyncpg is not: asyncpg spans the
    BEGIN and the ROLLBACK around a failed query, but never the query itself."""
    with pytest.raises(Exception):  # noqa: B017 — whatever the driver raises
        async with engine.connect() as connection:
            await connection.execute(text(MISSING_TABLE))

    failed = _statements(exporter)[MISSING_TABLE]
    assert failed.status.is_ok is False


def test_session_hands_its_engine_over():
    """The engine is only traced because `configure` passes it on. Nothing fails when
    that call goes missing — the queries just stop appearing."""
    assert "observability.instrument_engine(_engine)" in SESSION_MODULE.read_text()
