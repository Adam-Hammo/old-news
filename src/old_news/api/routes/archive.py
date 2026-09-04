"""The archive's half of the contract: what is held, and one shelf of it at a time."""

import uuid

from litestar import Router, get
from litestar.exceptions import ClientException
from litestar.params import Parameter

from old_news import ui
from old_news.config import get_settings

ZONE = Parameter(default="UTC", description="An IANA zone; months are grouped in it.")


@get("/archive", summary="What the archive holds, shelved by publication and by month.")
async def contents(zone: str = ZONE) -> ui.Contents:
    try:
        return await ui.contents(zone=zone)
    except ui.BadShelf as exc:
        raise ClientException(detail=f"unusable zone: {exc}") from exc


@get("/archive/search", summary="What the terms reach, best first, across every reading held.")
async def search(
    q: str = Parameter(default="", description="Words, not query syntax. Every one is meant."),
    after: str = Parameter(default="", description="The cursor a previous page ended on."),
    limit: int = Parameter(default=ui.DEFAULT_LIMIT, ge=1, le=ui.MAX_LIMIT),
) -> ui.Found:
    try:
        return await ui.look(get_settings().kindle, terms=q, after=after, limit=limit)
    except ui.BadQuery as exc:
        raise ClientException(detail=f"unusable search: {exc}") from exc


@get("/archive/items", summary="One shelf of the archive: a publication, a month, or both.")
async def shelf(
    feed: uuid.UUID | None = Parameter(default=None, description="A feed's whole run."),
    month: str = Parameter(default="", description="A month as YYYY-MM, in `zone`."),
    tier: str = Parameter(default="", description="Only feeds filed at this tier or above."),
    after: str = Parameter(default="", description="The cursor a previous page ended on."),
    limit: int = Parameter(default=ui.DEFAULT_LIMIT, ge=1, le=ui.MAX_LIMIT),
    zone: str = ZONE,
) -> ui.Listing:
    try:
        return await ui.shelf(
            get_settings().kindle,
            feed=feed,
            month=month,
            tier=tier,
            after=after,
            limit=limit,
            zone=zone,
        )
    except ui.BadShelf as exc:
        raise ClientException(detail=f"no such shelf: {exc}") from exc
    except ui.BadCursor as exc:
        raise ClientException(detail="unreadable cursor") from exc


def archive_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[contents, search, shelf], tags=["archive"])
