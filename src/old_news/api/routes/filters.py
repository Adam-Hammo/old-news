"""Managing what the reader never wants to see."""

import dataclasses
import uuid

from litestar import Router, delete, get, post
from litestar.exceptions import ClientException, HTTPException, NotFoundException
from litestar.params import FromPath

from old_news.db import Dimension
from old_news.filters import service


@dataclasses.dataclass(frozen=True, slots=True)
class NewFilter:
    """A pattern to block, everywhere or on one feed."""

    # `title_phrase` or `url_pattern`.
    dimension: str
    # Matched as a case-insensitive substring.
    pattern: str
    # Null is every feed.
    feed_id: uuid.UUID | None = None
    note: str = ""


@get("/filters", summary="Every filter, and what it blocks.")
async def filtering() -> tuple[service.Blocking, ...]:
    return await service.listing()


@post("/filters", summary="Block what matches a pattern.", status_code=201)
async def block(data: NewFilter) -> None:
    if data.dimension not in set(Dimension):
        raise ClientException(detail=f"not a dimension: {data.dimension}")
    if not (pattern := data.pattern.strip()):
        raise ClientException(detail="an empty pattern would block everything")

    try:
        added = await service.add(
            data.dimension, pattern, feed_id=data.feed_id, note=data.note.strip()
        )
    except service.UnknownFeed as exc:
        raise ClientException(detail="not a feed we know") from exc

    if not added:
        raise HTTPException(status_code=409, detail="already filtering that")


@delete("/filters/{filter_id:uuid}", summary="Stop filtering. What it hid comes back.")
async def unblock(filter_id: FromPath[uuid.UUID]) -> None:
    if not await service.remove(filter_id):
        raise NotFoundException(detail="not a filter")


def filters_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[filtering, block, unblock], tags=["filters"])
