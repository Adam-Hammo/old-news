"""Job spans, and the trace context that links them to whatever deferred them.

Procrastinate has no notion of metadata on a job, so the W3C traceparent travels
as a reserved kwarg. `task()` strips it before the function is called, so task
signatures never see it.
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from procrastinate import App
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.job_context import JobContext

from old_news.observability import count, span

TRACE_KEY = "__traceparent"

# Housekeeping that runs on a timer forever. Failures still count and still log.
UNTRACED_TASKS = frozenset({"queue_metrics", "prune_jobs"})

# `messaging.*` below is OpenTelemetry's convention, not ours — it is what makes
# the backend read these spans as a queue.
MESSAGING_SYSTEM = "procrastinate"

_propagator = TraceContextTextMapPropagator()


def carrier() -> dict[str, str]:
    """The current trace context, flattened for storage alongside a job's kwargs."""
    into: dict[str, str] = {}
    _propagator.inject(into)
    return into


def context_from(task_kwargs: dict[str, Any]) -> Context | None:
    stored = task_kwargs.get(TRACE_KEY)
    return _propagator.extract(stored) if stored else None


async def trace_jobs(
    call_next: Callable[[], Awaitable[Any]], context: JobContext, worker: Any
) -> Any:
    """Worker middleware: one span per job, parented to whatever deferred it."""
    job = context.job

    if job.task_name in UNTRACED_TASKS:
        try:
            return await call_next()
        except Exception:
            count("queue.jobs.failed", task=job.task_name, queue=job.queue)
            raise

    attributes = {
        "job.id": job.id,
        "job.queue": job.queue,
        "job.task": job.task_name,
        "job.attempts": job.attempts,
        "job.priority": job.priority,
        "worker.name": context.worker_name,
        "messaging.system": MESSAGING_SYSTEM,
        "messaging.destination.name": job.queue,
        "messaging.operation.name": "process",
        "messaging.operation.type": "process",
        "messaging.message.id": str(job.id),
    }

    with span(f"task {job.task_name}", context=context_from(job.task_kwargs), **attributes) as s:
        try:
            result = await call_next()
        except Exception as exc:
            s.record_exception(exc)
            count("queue.jobs.failed", task=job.task_name, queue=job.queue)
            raise
        count("queue.jobs.succeeded", task=job.task_name, queue=job.queue)
        return result


def task(app: App, **options: Any) -> Callable[[Callable[..., Any]], Any]:
    """Like `app.task`, but tolerates the traceparent that `defer` attaches."""

    def decorator(fn: Callable[..., Any]) -> Any:
        @functools.wraps(fn)
        async def strip_traceparent(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop(TRACE_KEY, None)
            return await fn(*args, **kwargs)

        return app.task(**options)(strip_traceparent)

    return decorator


def _destination(registered_task: Any) -> tuple[str, str]:
    """`Task.configure()` returns a JobDeferrer, so both shapes reach `defer` and
    only one of them has a `.job`."""
    job = getattr(registered_task, "job", None)
    if job is not None:
        return job.queue, job.task_name
    return registered_task.queue, registered_task.name


async def defer(registered_task: Any, /, **kwargs: Any) -> Any:
    """Defer a job carrying the current trace context.

    Without the send span a job deferred by a periodic task parents to nothing.
    """
    queue, task_name = _destination(registered_task)
    attributes: dict[str, Any] = {
        "job.queue": queue,
        "job.task": task_name,
        "messaging.system": MESSAGING_SYSTEM,
        "messaging.destination.name": queue,
        "messaging.operation.name": "send",
        "messaging.operation.type": "send",
    }

    with span(f"send {queue}", **attributes):
        # Inside the span, so `carrier()` captures it and the job becomes its child.
        return await registered_task.defer_async(**kwargs, **{TRACE_KEY: carrier()})


async def defer_unless_queued(registered_task: Any, /, **kwargs: Any) -> bool:
    """Defer, unless the queueing lock says one is already waiting.

    A queueing lock is a request to skip a duplicate, but procrastinate expresses
    the collision as an exception — so an unhandled one kills the whole sweep and
    every job it had not deferred yet. Jobs now wait on a per-host lock, so one
    still queued a minute later is ordinary rather than exceptional.
    """
    try:
        await defer(registered_task, **kwargs)
    except AlreadyEnqueued:
        return False
    return True
