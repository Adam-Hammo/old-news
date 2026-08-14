from litestar import Router, get
from litestar.exceptions import ServiceUnavailableException
from sqlalchemy import text

from old_news import __version__, db
from old_news.tasks.app import app as queue_app
from old_news.tasks.maintenance import JOB_STATUSES, STALLED_AFTER_SECONDS


@get("/live", summary="Liveness — process is up, nothing else checked.")
async def live() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@get("/ready", summary="Readiness — Postgres answers.")
async def ready() -> dict[str, str]:
    try:
        async with db.session() as current:
            await current.execute(text("SELECT 1"))
    except Exception as exc:
        raise ServiceUnavailableException(detail=f"database unreachable: {exc}") from exc
    return {"status": "ok", "database": "ok"}


@get("/queue", summary="Queue depth and stalled workers, without needing Logfire.")
async def queue() -> dict[str, int]:
    manager = queue_app.job_manager

    depth = dict.fromkeys(JOB_STATUSES, 0)
    for row in await manager.list_queues_async():
        for status in JOB_STATUSES:
            depth[status] += row[status]

    stalled = await manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER_SECONDS)
    return depth | {"stalled": len(list(stalled))}


def health_router(path: str = "/health") -> Router:
    return Router(path=path, route_handlers=[live, ready, queue], tags=["health"])
