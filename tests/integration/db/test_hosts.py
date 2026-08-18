"""Hosts as the aggregate root: feeds and robots rules hang off one publisher."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, robots
from old_news.db import Feed, Host
from old_news.politeness import resolve
from old_news.subscriptions.service import UnpollableUrl, add


@db.transactional
async def _hosts(session: AsyncSession) -> list[str]:
    return sorted((await session.execute(select(Host.name))).scalars().all())


@db.transactional
async def _host_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Host))).scalar_one()


async def test_two_feeds_from_one_publisher_share_a_host_row(clean: None):
    """The whole point: one publisher, one set of rules, one politeness group."""
    await add("https://www.theguardian.com/au/rss")
    await add("https://www.theguardian.com/world/rss")

    assert await _hosts() == ["theguardian.com"]

    async with db.session() as session:
        ids = (await session.execute(select(Feed.host_id))).scalars().all()
    assert len(set(ids)) == 1


async def test_resolving_the_same_host_twice_makes_one_row(clean: None):
    async with db.session() as session:
        first = await resolve(session, "https://example.com/a.xml")
        second = await resolve(session, "https://www.example.com/b.xml")

    assert first == second
    assert await _host_count() == 1


async def test_a_url_with_nothing_to_poll_is_refused(clean: None):
    """`feeds.host_id` is not nullable, so this cannot be fudged."""
    with pytest.raises(UnpollableUrl):
        await add("newsletter:0:someone@example.com")

    assert await _host_count() == 0


async def test_a_feed_and_its_robots_rules_share_one_host(clean: None, no_policies: None):
    """Asking about a host the feeds already know must not invent a second one."""
    await add("https://example.com/feed.xml")

    assert await robots.crawl_delays(["example.com"]) == {}
    assert await robots.stale_hosts(["example.com"], limit=5) == ["example.com"]
    assert await _host_count() == 1
