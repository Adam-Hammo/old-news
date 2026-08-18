"""robots.txt against a real Postgres and a real socket."""

import datetime
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from old_news import db, robots
from old_news.db import Host
from old_news.fetch import Fetcher
from old_news.robots.service import UNREACHABLE_STATUS

BLANKET = b"User-agent: *\nDisallow: /\n"
TARGETED = b"User-agent: *\nDisallow: /feeds/\n"

ROBOTS = b"""User-agent: *
Crawl-delay: 7
Disallow: /print/

User-agent: old-news
Crawl-delay: 12
Disallow: /members/
"""


@pytest.fixture
def server(http_server) -> str:
    return http_server({"/robots.txt": (200, ROBOTS, {})})


@pytest.fixture
def blanket_ban(http_server) -> str:
    return http_server({"/robots.txt": (200, BLANKET, {})})


@pytest.fixture
def targeted_ban(http_server) -> str:
    return http_server({"/robots.txt": (200, TARGETED, {})})


@pytest.fixture
async def fetcher(settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


async def test_a_hosts_rules_are_fetched_and_stored(
    no_policies: None, server: str, fetcher: Fetcher, settings
):
    stored = await robots.refresh("example.com", fetcher, settings, origin=server)

    assert stored.status == 200
    # Keyed by the host entity, not by a loose string.
    async with db.session() as session:
        host = await session.get(Host, stored.host_id)
    assert host is not None
    assert host.name == "example.com"
    # The body is kept, so the rules can be re-derived when the parsing improves.
    assert "Disallow: /members/" in stored.body
    # Our own record's delay, not the one under `*`.
    assert stored.crawl_delay_seconds == 12.0
    assert stored.expires_at > stored.fetched_at


async def test_refreshing_twice_overwrites_rather_than_accumulates(
    no_policies: None, server: str, fetcher: Fetcher, settings
):
    """A cache row, not archive — one row per host, however often it is refreshed."""
    for _ in range(3):
        await robots.refresh("example.com", fetcher, settings, origin=server)

    async with db.session() as session:
        rows = await session.execute(text("SELECT count(*) FROM robots_policies"))

    assert rows.scalar_one() == 1


async def test_an_unreachable_host_is_recorded_and_carried_on_past(
    no_policies: None, fetcher: Fetcher, settings
):
    """A publisher that can't tell us its rules hasn't told us to stop."""
    stored = await robots.refresh("127.0.0.1:1", fetcher, settings, origin="http://127.0.0.1:1")

    assert stored.status == UNREACHABLE_STATUS
    assert stored.error
    assert stored.crawl_delay_seconds is None
    assert await robots.allows("https://127.0.0.1:1/anything", settings) is True
    # Retried on the shorter clock than a host that answered.
    ttl = (stored.expires_at - stored.fetched_at).total_seconds()
    assert ttl == pytest.approx(settings.robots.failure_ttl_seconds, abs=1)


async def test_a_stored_disallow_is_obeyed(
    no_policies: None, server: str, fetcher: Fetcher, settings
):
    await robots.refresh("example.com", fetcher, settings, origin=server)

    assert await robots.allows("https://example.com/members/secret", settings) is False
    assert await robots.allows("https://example.com/news/story", settings) is True
    # The `*` record's Disallow is not ours, because we have a record of our own.
    assert await robots.allows("https://example.com/print/story", settings) is True


async def test_a_host_nothing_is_stored_for_is_allowed(no_policies: None, settings):
    """A missing policy means the sweep hasn't got there, not that fetching is banned."""
    assert await robots.allows("https://never-asked.example/x", settings) is True


async def test_crawl_delays_come_back_for_the_batch(
    no_policies: None, server: str, fetcher: Fetcher, settings
):
    await robots.refresh("example.com", fetcher, settings, origin=server)

    delays = await robots.crawl_delays(["example.com", "never-asked.example", ""])

    assert delays == {"example.com": 12.0}


async def test_stale_hosts_are_the_unasked_and_the_expired(
    no_policies: None, server: str, fetcher: Fetcher, settings
):
    await robots.refresh("fresh.example", fetcher, settings, origin=server)
    expired = await robots.refresh("stale.example", fetcher, settings, origin=server)

    async with db.session() as session:
        await session.execute(
            text("UPDATE robots_policies SET expires_at = :past WHERE host_id = :host_id"),
            {
                "past": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
                "host_id": expired.host_id,
            },
        )

    stale = await robots.stale_hosts(["fresh.example", "stale.example", "new.example"], limit=10)

    assert stale == ["new.example", "stale.example"]


async def test_the_refresh_batch_is_bounded(no_policies: None, settings):
    hosts = [f"h{n}.example" for n in range(10)]

    assert len(await robots.stale_hosts(hosts, limit=3)) == 3


async def test_a_targeted_disallow_stops_a_poll(
    no_policies: None, targeted_ban: str, fetcher: Fetcher, settings
):
    await robots.refresh("picky.example", fetcher, settings, origin=targeted_ban)

    assert await robots.allows_poll("https://picky.example/feeds/uk.xml", settings) is False
    assert await robots.allows_poll("https://picky.example/rss.xml", settings) is True


async def test_a_blanket_ban_does_not_stop_a_poll(
    no_policies: None, blanket_ban: str, fetcher: Fetcher, settings
):
    """A site publishing RSS while banning all bots is stating a crawler policy, not
    withdrawing the feed it published."""
    await robots.refresh("walled.example", fetcher, settings, origin=blanket_ban)

    assert await robots.allows_poll("https://walled.example/feed.xml", settings) is True
    # An article fetch is a different question, and still gets refused.
    assert await robots.allows("https://walled.example/story", settings) is False


async def test_an_unknown_host_may_be_polled(no_policies: None, settings):
    assert await robots.allows_poll("https://never-asked.example/feed.xml", settings) is True
