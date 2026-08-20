from pydantic import BaseModel, Field


class WorkerSettings(BaseModel):
    """How much of the worker each queue gets.

    One pool per queue rather than one pool over all of them: re-reading the archive and
    polling for new articles share a process, and a few thousand queued extractions must
    not occupy every slot the polls need.

    Every queue any task declares has to appear here or nothing serves it — including
    `default`, which is where the heartbeat and the nightly maintenance live, and
    `builtin`, which is procrastinate's own. `test_queue.py` checks the set.
    """

    concurrency: dict[str, int] = Field(
        default_factory=lambda: {"ingest": 2, "pages": 4, "default": 1, "builtin": 1}
    )
