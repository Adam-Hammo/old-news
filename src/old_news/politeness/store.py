"""Resolving the host a URL belongs to, as a foreign key. The one place that does it."""

import dataclasses
import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Feed, Host, RobotsPolicy, Subscription
from old_news.politeness.hosts import host_of


@dataclasses.dataclass(frozen=True, slots=True)
class Publisher:
    """One host we visit, and everything learned about how to be polite to it."""

    name: str
    feeds: int
    # Some publishers link articles at an apex that resolves nowhere; this is learned.
    requires_www: bool
    # What robots.txt asked for. Null is a host that asked for nothing.
    crawl_delay_seconds: float | None
    # 0 is a host that could not be reached, which is not an HTTP status at all.
    robots_status: int
    robots_fetched_at: datetime.datetime | None
    robots_expires_at: datetime.datetime | None
    capture_failures: int


async def ensure(session: AsyncSession, name: str) -> uuid.UUID:
    """The host row for a name, created if new. Two feeds arriving at once both succeed."""
    found = await _id_of(session, name)
    if found is not None:
        return found
    await session.execute(insert(Host).values(name=name).on_conflict_do_nothing())
    created = await _id_of(session, name)
    if created is None:
        raise LookupError(f"host {name} vanished between insert and read")
    return created


async def _id_of(session: AsyncSession, name: str) -> uuid.UUID | None:
    return (await session.execute(select(Host.id).where(Host.name == name))).scalar_one_or_none()


async def resolve(session: AsyncSession, url: str) -> uuid.UUID | None:
    """The host a URL belongs to. None when it names none, and so can't be polled."""
    name = host_of(url)
    return await ensure(session, name) if name else None


@db.transactional
async def publishers(session: AsyncSession) -> tuple[Publisher, ...]:
    """Every host behind a feed we follow. Nothing here is set by hand — it is all learned."""
    rows = await session.execute(
        select(
            Host.name,
            func.count(Feed.id.distinct()).label("feeds"),
            Host.requires_www,
            func.min(RobotsPolicy.crawl_delay_seconds).label("crawl_delay_seconds"),
            func.coalesce(func.min(RobotsPolicy.status), 0).label("robots_status"),
            func.min(RobotsPolicy.fetched_at).label("robots_fetched_at"),
            func.min(RobotsPolicy.expires_at).label("robots_expires_at"),
            Host.capture_failures.label("capture_failures"),
        )
        .select_from(Host)
        .join(Feed, Feed.host_id == Host.id)
        .join(Subscription, Subscription.feed_id == Feed.id)
        .outerjoin(RobotsPolicy, RobotsPolicy.host_id == Host.id)
        .where(Subscription.active.is_(True))
        .group_by(Host.id, Host.name, Host.requires_www)
        .order_by(Host.name)
    )
    return tuple(Publisher(**row) for row in rows.mappings())
