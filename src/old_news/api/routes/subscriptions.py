"""Managing what we follow. The half of subscriptions that had no interface at all."""

import dataclasses
import uuid

from litestar import Router, delete, get, patch, post
from litestar.exceptions import ClientException, HTTPException, NotFoundException
from litestar.params import FromPath

from old_news import fetch
from old_news.db import Tier
from old_news.subscriptions import service


@dataclasses.dataclass(frozen=True, slots=True)
class NewFeed:
    """A pasted address, which may be a feed or a page that names one."""

    url: str
    category: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Filing:
    """Every per-feed choice, sent whole: a partial one cannot say "never expires"."""

    # Empty is unfiled, which the river still carries.
    category: str
    # `wire`, `archive` or `kindle`. The levels nest, so kindle takes what archive does.
    tier: str = Tier.WIRE
    # Null is a feed nothing ages out of.
    expires_after_seconds: int | None = None


@get("/subscriptions", summary="Every feed we follow, and how it is filed.")
async def following() -> tuple[service.Following, ...]:
    return await service.listing()


@post("/subscriptions", summary="Follow a feed, or a page that names one.", status_code=201)
async def follow(data: NewFeed) -> None:
    try:
        feed = await service.subscribe(data.url, fetch.client(), category=data.category)
    except service.UnpollableUrl as exc:
        raise ClientException(detail="that is not an address we can poll") from exc
    except service.NoFeedFound as exc:
        raise ClientException(detail="no feed there, and the page names none") from exc

    if feed is None:
        raise HTTPException(status_code=409, detail="already following that one")


@patch("/subscriptions/{feed_id:uuid}", summary="Set how a feed is filed.", status_code=204)
async def refile(feed_id: FromPath[uuid.UUID], data: Filing) -> None:
    if data.tier not in set(Tier):
        raise ClientException(detail=f"not a tier: {data.tier}")

    filed = await service.refile(
        feed_id,
        category=data.category,
        tier=data.tier,
        expires_after_seconds=data.expires_after_seconds,
    )
    if not filed:
        raise NotFoundException(detail="not a feed we follow")


@delete("/subscriptions/{feed_id:uuid}", summary="Stop following, keeping the archive.")
async def unfollow(feed_id: FromPath[uuid.UUID]) -> None:
    if not await service.drop(feed_id):
        raise NotFoundException(detail="not a feed we follow")


def subscriptions_router(path: str = "/") -> Router:
    return Router(
        path=path,
        route_handlers=[following, follow, refile, unfollow],
        tags=["subscriptions"],
    )
