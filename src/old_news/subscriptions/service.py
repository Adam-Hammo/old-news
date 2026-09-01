"""Managing what we are subscribed to. Operator-triggered, unlike polling."""

import datetime
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher, fetchable
from old_news.politeness import resolve
from old_news.subscriptions import discover, opml

logger = logging.getLogger(__name__)


class UnpollableUrl(ValueError):
    """No host, so nothing to poll. `feeds.host_id` is not nullable by design."""


class NoFeedFound(ValueError):
    """Not a feed, and the page it served names none."""


@dataclass(frozen=True, slots=True)
class Following:
    """One feed we follow, as a screen for managing them needs it."""

    id: uuid.UUID
    title: str
    url: str
    site_url: str
    category: str
    last_success_at: datetime.datetime | None


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


async def _following(session: AsyncSession, where: ColumnElement[bool]) -> Subscription | None:
    return (
        await session.execute(
            select(Subscription).join(Feed, Feed.id == Subscription.feed_id).where(where)
        )
    ).scalar_one_or_none()


@db.transactional
async def unsubscribe(session: AsyncSession, url: str) -> bool:
    """Stop polling without touching the archive. The feed and its items remain."""
    return _drop(await _following(session, Feed.url == url))


@db.transactional
async def drop(session: AsyncSession, feed_id: uuid.UUID) -> bool:
    """`unsubscribe`, keyed the way a screen with rows on it has to key it."""
    return _drop(await _following(session, Feed.id == feed_id))


def _drop(subscription: Subscription | None) -> bool:
    if subscription is None or not subscription.active:
        return False
    subscription.active = False
    return True


@db.transactional
async def already_following(session: AsyncSession, url: str) -> bool:
    """Whether this exact address is one we follow. Asked before reaching for the network."""
    subscription = await _following(session, Feed.url == url)
    return subscription is not None and subscription.active


@db.transactional
async def refile(session: AsyncSession, feed_id: uuid.UUID, category: str) -> bool:
    """Move a feed to another section. Empty is unfiled, which the river still carries."""
    subscription = await _following(session, Feed.id == feed_id)
    if subscription is None or not subscription.active:
        return False
    subscription.category = category
    return True


@db.transactional
async def listing(session: AsyncSession) -> tuple[Following, ...]:
    """Everything we follow, filed the way the river slices it."""
    rows = await session.execute(
        select(
            Feed.id,
            Feed.title,
            Feed.url,
            Feed.site_url,
            Subscription.category,
            Feed.last_success_at,
        )
        .join(Subscription, Subscription.feed_id == Feed.id)
        .where(Subscription.active.is_(True))
        .order_by(Subscription.category, Feed.title, Feed.url)
    )
    return tuple(Following(*row) for row in rows.all())


async def subscribe(url: str, fetcher: Fetcher, *, category: str = "") -> Feed | None:
    """Follow whatever somebody pasted: a feed, or a page naming one. None if already on."""
    if not fetchable(url):
        raise UnpollableUrl(url)
    # Before the fetch, or pasting a feed twice reports whatever the network said.
    if await already_following(url):
        return None

    found = await discover.discover(url, fetcher)
    if found is None:
        raise NoFeedFound(url)

    return await add(found, category=category, site_url="" if found == url else url)


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
