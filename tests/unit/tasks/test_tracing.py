from typing import Any

import logfire
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from procrastinate.job_context import JobContext
from procrastinate.jobs import Job

from old_news.observability import span
from old_news.tasks.tracing import TRACE_KEY, carrier, context_from, defer, trace_jobs


@pytest.fixture
def exporter() -> TestExporter:
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    return exporter


def spans_named(exporter: TestExporter, name: str) -> list:
    """Logfire emits a pending span alongside each real one; only the real one matters."""
    return [
        s
        for s in exporter.exported_spans
        if s.name == name and (s.attributes or {}).get("logfire.span_type") != "pending_span"
    ]


def job_context(
    task_kwargs: dict[str, Any] | None = None, *, task_name: str = "heartbeat"
) -> JobContext:
    job = Job(
        id=42,
        status="doing",
        queue="default",
        priority=0,
        lock=None,
        queueing_lock=None,
        task_name=task_name,
        task_kwargs=dict(task_kwargs or {}),
        scheduled_at=None,
        attempts=1,
    )
    return JobContext(
        job=job,
        worker_name="worker-0",
        worker_queues=None,
        app=None,  # ty: ignore[invalid-argument-type]
        start_timestamp=0.0,
        abort_reason=lambda: None,
    )


async def test_a_job_gets_its_own_span(exporter: TestExporter):
    async def call_next() -> str:
        return "done"

    result = await trace_jobs(call_next, job_context(), None)

    assert result == "done"
    [job_span] = spans_named(exporter, "task heartbeat")
    assert job_span.attributes["job.id"] == 42
    assert job_span.attributes["job.task"] == "heartbeat"
    assert job_span.attributes["job.queue"] == "default"


async def test_failures_are_recorded_and_re_raised(exporter: TestExporter):
    async def call_next() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await trace_jobs(call_next, job_context(), None)

    [job_span] = spans_named(exporter, "task heartbeat")
    assert any(event.name == "exception" for event in job_span.events)


async def test_task_kwargs_never_reach_the_span(exporter: TestExporter):
    """Kwargs carry feed URLs now and article content later. Span attributes aren't scrubbed."""

    async def call_next() -> None:
        return None

    await trace_jobs(call_next, job_context({"url": "https://example.com/feed?key=SECRET"}), None)

    [job_span] = spans_named(exporter, "task heartbeat")
    assert "SECRET" not in str(job_span.attributes)


async def test_the_job_span_is_a_child_of_whatever_deferred_it(exporter: TestExporter):
    async def call_next() -> None:
        return None

    with span("deferring"):
        stored = carrier()

    await trace_jobs(call_next, job_context({TRACE_KEY: stored}), None)

    [parent] = spans_named(exporter, "deferring")
    [child] = spans_named(exporter, "task heartbeat")

    assert child.context.trace_id == parent.context.trace_id
    assert child.parent.span_id == parent.context.span_id


def test_context_is_absent_when_nothing_was_propagated():
    assert context_from({}) is None


class FakeTask:
    """What `app.task` returns."""

    queue = "ingest"
    name = "poll_feed"

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    async def defer_async(self, **kwargs: Any) -> int:
        self._captured.update(kwargs)
        return 1


class FakeDeferrer(FakeTask):
    """What `task.configure(...)` returns: the names move onto a job."""

    queue = None
    name = None

    def __init__(self, captured: dict[str, Any]) -> None:
        super().__init__(captured)
        self.job = job_context().job


async def test_defer_attaches_the_current_context():
    captured: dict[str, Any] = {}

    with span("outer"):
        await defer(FakeTask(captured), note="hello")

    assert captured["note"] == "hello"
    assert "traceparent" in captured[TRACE_KEY]


async def test_defer_emits_a_send_span(exporter: TestExporter):
    [send] = await _defer_and_collect(exporter, FakeTask({}))

    assert send.attributes["messaging.destination.name"] == "ingest"
    assert send.attributes["messaging.operation.type"] == "send"
    assert send.attributes["job.task"] == "poll_feed"


async def test_defer_reads_a_configured_task_through_its_job(exporter: TestExporter):
    """`Task.configure()` hands `defer` a JobDeferrer, which names neither."""
    [send] = await _defer_and_collect(exporter, FakeDeferrer({}), queue="default")

    assert send.attributes["messaging.destination.name"] == "default"
    assert send.attributes["job.task"] == "heartbeat"


async def _defer_and_collect(
    exporter: TestExporter, task: FakeTask, *, queue: str = "ingest"
) -> list:
    await defer(task)
    return spans_named(exporter, f"send {queue}")


async def test_a_job_parents_to_the_send_span(exporter: TestExporter):
    """The whole point of the traceparent: one trace from schedule to poll."""
    captured: dict[str, Any] = {}

    async def call_next() -> None:
        return None

    await defer(FakeTask(captured), note="hi")
    await trace_jobs(call_next, job_context({TRACE_KEY: captured[TRACE_KEY]}), None)

    [send] = spans_named(exporter, "send ingest")
    [job_span] = spans_named(exporter, "task heartbeat")

    assert job_span.parent.span_id == send.context.span_id


async def test_housekeeping_tasks_emit_no_span(exporter: TestExporter):
    """queue_metrics runs every minute forever; a successful run says nothing."""

    async def call_next() -> None:
        return None

    await trace_jobs(call_next, job_context(task_name="queue_metrics"), None)

    assert spans_named(exporter, "task queue_metrics") == []


async def test_real_work_is_still_traced(exporter: TestExporter):
    async def call_next() -> None:
        return None

    await trace_jobs(call_next, job_context(), None)

    assert spans_named(exporter, "task heartbeat") != []
