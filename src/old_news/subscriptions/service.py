"""Managing what we are subscribed to. Operator-triggered, unlike polling."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher, fetchable
from old_news.politeness import resolve
from old_news.subscriptions import discover, opml

logger = logging.getLogger(__name__)


class UnpollableUrl(ValueError):
    """No host, so nothing to poll. `feeds.host_id` is not nullable by design."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int = 0
    already_present: int = 0
    undiscoverable: tuple[str, ...] = ()
    unfetchable: tuple[str, ...] = ()


@db.transactional
async def add(
    session: AsyncSession,
    url: str,
    *,
    title: str = "",
    category: str = "",
    site_url: str = "",
) -> Feed | None:
    """Subscribe, reactivating a dropped feed rather than starting again. None if already on."""
    feed = (await session.execute(select(Feed).where(Feed.url == url))).scalar_one_or_none()

    if feed is None:
        host_id = await resolve(session, url)
        if host_id is None:
            raise UnpollableUrl(url)
        feed = Feed(url=url, title=title, site_url=site_url, host_id=host_id)
        session.add(feed)
        await session.flush()
        session.add(Subscription(feed_id=feed.id, category=category))
        return feed

    subscription = (
        await session.execute(select(Subscription).where(Subscription.feed_id == feed.id))
    ).scalar_one_or_none()

    if subscription is None:
        session.add(Subscription(feed_id=feed.id, category=category))
        return feed
    if not subscription.active:
        subscription.active = True
        return feed
    return None


async def import_opml(data: bytes, fetcher: Fetcher) -> ImportResult:
    """Add every subscription in an OPML file, discovering feeds where needed."""
    added = present = 0
    failed: list[str] = []
    unfetchable: list[str] = []

    for outline in opml.parse(data):
        url, site_url = outline.url, outline.site_url

        # An OPML file is a list of things somebody subscribed to, not a list of
        # feeds — exporters put email newsletters and other non-web entries in it.
        if not fetchable(url):
            unfetchable.append(url)
            continue

        if outline.needs_discovery:
            found = await discover.discover(url, fetcher)
            if found is None:
                failed.append(url)
                continue
            url, site_url = found, outline.url

        feed = await add(url, title=outline.title, category=outline.category, site_url=site_url)
        if feed is None:
            present += 1
        else:
            added += 1

    return ImportResult(added, present, tuple(failed), tuple(unfetchable))


@db.transactional
async def unsubscribe(session: AsyncSession, url: str) -> bool:
    """Stop polling without touching the archive. The feed and its items remain."""
    subscription = (
        await session.execute(
            select(Subscription).join(Feed, Feed.id == Subscription.feed_id).where(Feed.url == url)
        )
    ).scalar_one_or_none()
    if subscription is None or not subscription.active:
        return False
    subscription.active = False
    return True


@db.transactional
async def _subscribed_rows(session: AsyncSession) -> list[tuple[Feed, Subscription]]:
    return list(
        (
            await session.execute(
                select(Feed, Subscription)
                .join(Subscription, Subscription.feed_id == Feed.id)
                .where(Subscription.active.is_(True))
                .order_by(Subscription.category, Feed.title)
            )
        ).all()
    )


async def export_opml() -> bytes:
    """Only what we currently follow — an OPML file is a subscription list."""
    rows = await _subscribed_rows()

    return opml.render(
        [
            opml.Outline(
                url=feed.url,
                title=feed.title,
                category=subscription.category,
                site_url=feed.site_url,
            )
            for feed, subscription in rows
        ]
    )
