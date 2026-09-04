from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.handlers import asgi
from litestar.openapi import OpenAPIConfig
from litestar.plugins.opentelemetry import OpenTelemetryPlugin

from old_news import __version__, db, fetch, observability
from old_news.api.routes import (
    archive_router,
    health_router,
    reading_router,
    reports_router,
    subscriptions_router,
)
from old_news.config import Settings, get_settings
from old_news.tasks import app as queue_app


@asynccontextmanager
async def _lifespan(_app: Litestar) -> AsyncGenerator[None]:
    # `/health/queue` reads queue state, which needs procrastinate's own connection open here.
    async with queue_app.open_async():
        try:
            yield
        finally:
            await fetch.dispose()
            await db.dispose()


def create_app(settings: Settings | None = None) -> Litestar:
    settings = settings or get_settings()
    observability.configure(settings.telemetry, environment=settings.environment, component="api")

    engine = db.configure(settings.database)
    fetch.configure(settings.http)

    handlers = [
        archive_router(),
        health_router(),
        reading_router(),
        reports_router(),
        subscriptions_router(),
    ]
    if settings.admin.enabled:
        if settings.environment == "production" and not settings.admin.configured:
            raise RuntimeError(
                "admin is enabled without OLD_NEWS_ADMIN__PASSWORD_HASH; run `just admin-password`"
            )

        from old_news.api.admin import create_admin

        # copy_scope keeps sqladmin's scope mutations from leaking back into
        # Litestar. It is the Litestar 3 default.
        handlers.append(
            asgi(settings.admin.path, is_mount=True, copy_scope=True)(
                create_admin(engine, settings.admin)
            )
        )

    return Litestar(
        route_handlers=handlers,
        lifespan=[_lifespan],
        plugins=[OpenTelemetryPlugin(observability.litestar_config())],
        before_request=observability.name_span_after_route,
        debug=settings.api.debug,
        openapi_config=OpenAPIConfig(title="old-news", version=__version__, path="/schema"),
    )
