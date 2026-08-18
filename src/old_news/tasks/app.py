from procrastinate import App, PsycopgConnector

from old_news.config import get_settings
from old_news.tasks.tracing import trace_jobs

# Task modules are imported by the worker at startup; listing them here keeps
# registration out of __init__ and avoids an import cycle.
app = App(
    connector=PsycopgConnector(conninfo=get_settings().database.psycopg_url),
    import_paths=[
        "old_news.tasks.maintenance",
        "old_news.tasks.ingest",
        "old_news.tasks.robots",
    ],
    worker_defaults={
        "worker_middleware": [trace_jobs],
        # Successful jobs leave no row behind. Postgres holds the queue; the
        # history lives in traces, where it can be queried and expires on its own.
        "delete_jobs": "successful",
    },
)
