"""The archive's half of the contract: what is held, and whatever the query reaches of it."""

from litestar import Router, get
from litestar.exceptions import ClientException
from litestar.params import Parameter

from old_news import ui
from old_news.config import get_settings

ZONE = Parameter(default="UTC", description="An IANA zone; months and dates are read in it.")


QUERY = Parameter(
    default="",
    description=(
        "Words, and the operators `from:` `by:` `after:` `before:` `is:`. A quoted run is "
        "adjacent, a leading minus excludes. Empty is everything held."
    ),
)


@get("/archive/facets", summary="What is in what the query reached, dimension by dimension.")
async def facets(q: str = QUERY, zone: str = ZONE) -> ui.Shape:
    try:
        return await ui.shape(asked=ui.parse(q), zone=zone)
    except ui.BadQuery as exc:
        raise ClientException(detail=f"unusable search: {exc}") from exc
    except ui.BadZone as exc:
        raise ClientException(detail=f"unusable zone: {exc}") from exc


@get("/archive/items", summary="Everything held that the query reaches, and how much did.")
async def held(
    q: str = QUERY,
    after: str = Parameter(default="", description="The cursor a previous page ended on."),
    limit: int = Parameter(default=ui.DEFAULT_LIMIT, ge=1, le=ui.MAX_LIMIT),
    zone: str = ZONE,
) -> ui.Found:
    try:
        return await ui.held(
            get_settings().kindle, asked=ui.parse(q), after=after, limit=limit, zone=zone
        )
    except ui.BadQuery as exc:
        raise ClientException(detail=f"unusable search: {exc}") from exc
    except ui.BadZone as exc:
        raise ClientException(detail=f"unusable zone: {exc}") from exc
    except ui.BadCursor as exc:
        raise ClientException(detail="unreadable cursor") from exc


def archive_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[facets, held], tags=["archive"])
