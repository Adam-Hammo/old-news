"""What the box is doing, for a screen that would otherwise be the admin panel. Read only."""

from litestar import Router, get

from old_news.config import visible
from old_news.politeness import store
from old_news.subscriptions import service


@get("/status/polling", summary="Every feed we follow, and how its polling is going.")
async def polling() -> tuple[service.Polling, ...]:
    return await service.polling()


@get("/status/publishers", summary="Every host we visit, and how politely.")
async def publishers() -> tuple[store.Publisher, ...]:
    return await store.publishers()


@get("/status/config", summary="Every effective setting, with the credentials left out.")
async def config() -> tuple[visible.Section, ...]:
    return visible.sections()


def status_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[polling, publishers, config], tags=["status"])
