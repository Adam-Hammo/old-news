"""The reading UI's half of the contract. Query-shaped: section, cursor, limit."""

import dataclasses
import datetime
import uuid

from litestar import Router, get, post
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import FromPath, Parameter

from old_news import ui


@dataclasses.dataclass(frozen=True, slots=True)
class Opened:
    """When an item was first opened. A second call does not move it."""

    read_at: datetime.datetime


@get("/river", summary="A page of the river, newest first by when we first saw it.")
async def river(
    section: str = Parameter(default="", description="A subscription category; empty is all."),
    after: str = Parameter(default="", description="The cursor a previous page ended on."),
    limit: int = Parameter(default=ui.DEFAULT_LIMIT, ge=1, le=ui.MAX_LIMIT),
) -> ui.River:
    try:
        return await ui.river(section=section, after=after, limit=limit)
    except ui.BadCursor as exc:
        raise ClientException(detail="unreadable cursor") from exc


@get("/items/{item_id:uuid}", summary="One article, with the fullest text held for it.")
async def article(item_id: FromPath[uuid.UUID]) -> ui.Article:
    found = await ui.article(item_id)
    if found is None:
        raise NotFoundException(detail="no such item")
    return found


@post("/items/{item_id:uuid}/opened", summary="Record that an item was opened.")
async def opened(item_id: FromPath[uuid.UUID]) -> Opened:
    at = await ui.mark_opened(item_id)
    if at is None:
        raise NotFoundException(detail="no such item")
    return Opened(read_at=at)


@get("/sections", summary="The categories a river can be sliced by.")
async def sections() -> tuple[str, ...]:
    return await ui.sections()


def reading_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[river, article, opened, sections], tags=["reading"])
