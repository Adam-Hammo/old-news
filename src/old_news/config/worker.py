from pydantic import BaseModel, Field


class WorkerSettings(BaseModel):
    """How much of the worker each queue gets. One pool per queue, so none can starve another.

    Every queue any task declares has to appear here or nothing serves it.
    """

    concurrency: dict[str, int] = Field(
        default_factory=lambda: {"ingest": 2, "pages": 4, "default": 1, "builtin": 1}
    )
