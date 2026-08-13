from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.datastructures import State
from litestar.openapi import OpenAPIConfig
from litestar.plugins.opentelemetry import OpenTelemetryPlugin

from old_news import __version__, observability
from old_news.api.routes import health_router
from old_news.config import Settings, get_settings
from old_news.db import DB
from old_news.fetch import Fetcher
from old_news.tasks import app as queue_app


@asynccontextmanager
async def _lifespan(app: Litestar) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings

    await DB.start_connection_pool(max_size=settings.database.pool_max_size)
    app.state.fetcher = Fetcher(settings.http)

    # The API reads queue state and will defer jobs from request handlers, both of
    # which need procrastinate's own connection open in this process too.
    async with queue_app.open_async():
        try:
            yield
        finally:
            await app.state.fetcher.aclose()
            await DB.close_connection_pool()


def create_app(settings: Settings | None = None) -> Litestar:
    settings = settings or get_settings()
    observability.configure(settings.telemetry, environment=settings.environment)

    return Litestar(
        route_handlers=[health_router()],
        lifespan=[_lifespan],
        state=State({"settings": settings}),
        plugins=[OpenTelemetryPlugin(observability.litestar_config())],
        debug=settings.api.debug,
        openapi_config=OpenAPIConfig(title="old-news", version=__version__, path="/schema"),
    )
