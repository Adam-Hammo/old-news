"""The reading UI's half of the contract. Query-shaped: section, cursor, limit."""

import dataclasses
import datetime
import uuid

from litestar import Response, Router, get, post
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import FromPath, Parameter

from old_news import ui
from old_news.config import get_settings

# The bytes at an id never change — one row per distinct bytes at a URL — so a phone
# that has fetched a picture once never asks again.
FOREVER = "public, max-age=31536000, immutable"


@dataclasses.dataclass(frozen=True, slots=True)
class Opened:
    """When an item was first opened. A second call does not move it."""

    read_at: datetime.datetime


@dataclasses.dataclass(frozen=True, slots=True)
class Finished:
    """When an article was first read to the bottom. A second call does not move it."""

    finished_at: datetime.datetime


@get("/river", summary="A page of the river, newest first by when we first saw it.")
async def river(
    section: str = Parameter(default="", description="A subscription category; empty is all."),
    after: str = Parameter(default="", description="The cursor a previous page ended on."),
    limit: int = Parameter(default=ui.DEFAULT_LIMIT, ge=1, le=ui.MAX_LIMIT),
) -> ui.Listing:
    try:
        return await ui.river(get_settings().kindle, section=section, after=after, limit=limit)
    except ui.BadCursor as exc:
        raise ClientException(detail="unreadable cursor") from exc


@get("/items/{item_id:uuid}", summary="One article, with every reading held for it.")
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


@post("/items/{item_id:uuid}/finished", summary="Record that an article was read to the bottom.")
async def finished(item_id: FromPath[uuid.UUID]) -> Finished:
    at = await ui.mark_finished(item_id)
    if at is None:
        raise NotFoundException(detail="no such item")
    return Finished(finished_at=at)


@get(
    "/images/{capture_id:uuid}",
    summary="One held image, as it is stored.",
    cache_control=None,
    media_type="application/octet-stream",
)
async def image(capture_id: FromPath[uuid.UUID]) -> Response[bytes]:
    """Served from the archive rather than the publisher, whose copy rots."""
    held = await ui.image(capture_id)
    if held is None:
        raise NotFoundException(detail="no such image")
    body, content_type = held
    return Response(
        body,
        media_type=content_type or "application/octet-stream",
        headers={"cache-control": FOREVER},
    )


@get("/sections", summary="The categories a river can be sliced by.")
async def sections() -> tuple[str, ...]:
    return await ui.sections()


def reading_router(path: str = "/") -> Router:
    return Router(
        path=path,
        route_handlers=[river, article, opened, finished, image, sections],
        tags=["reading"],
    )
