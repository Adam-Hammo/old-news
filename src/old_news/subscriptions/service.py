"""Managing what we are subscribed to. Operator-triggered, unlike polling."""

import logging
from dataclasses import dataclass

from sqlalchemy import select

from old_news import db
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher
from old_news.subscriptions import discover, opml

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int = 0
    already_present: int = 0
    undiscoverable: tuple[str, ...] = ()


async def add(url: str, *, title: str = "", category: str = "", site_url: str = "") -> Feed | None:
    """Subscribe. Returns None if the URL is already subscribed.

    A feed we once followed and dropped keeps its archive, so re-subscribing
    reactivates the existing row rather than starting again.
    """
    async with db.session() as session:
        feed = (await session.execute(select(Feed).where(Feed.url == url))).scalar_one_or_none()

        if feed is None:
            feed = Feed(url=url, title=title, site_url=site_url)
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


async def retarget(feed_id, new_url: str) -> None:
    """Follow a permanent redirect. Otherwise we chase the same 301 forever."""
    async with db.session() as session:
        feed = await session.get(Feed, feed_id)
        if feed is None or feed.url == new_url:
            return
        logger.info("feed %s moved to %s", feed.url, new_url)
        feed.url = new_url
        feed.etag = ""
        feed.last_modified = ""


async def import_opml(data: bytes, fetcher: Fetcher) -> ImportResult:
    """Add every subscription in an OPML file, discovering feeds where needed."""
    added = present = 0
    failed: list[str] = []

    for outline in opml.parse(data):
        url, site_url = outline.url, outline.site_url

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

    return ImportResult(added, present, tuple(failed))


async def unsubscribe(url: str) -> bool:
    """Stop polling without touching the archive. The feed and its items remain."""
    async with db.session() as session:
        subscription = (
            await session.execute(
                select(Subscription)
                .join(Feed, Feed.id == Subscription.feed_id)
                .where(Feed.url == url)
            )
        ).scalar_one_or_none()
        if subscription is None or not subscription.active:
            return False
        subscription.active = False
        return True


async def export_opml() -> bytes:
    """Only what we currently follow — an OPML file is a subscription list."""
    async with db.session() as session:
        rows = (
            await session.execute(
                select(Feed, Subscription)
                .join(Subscription, Subscription.feed_id == Feed.id)
                .where(Subscription.active.is_(True))
                .order_by(Subscription.category, Feed.title)
            )
        ).all()

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
