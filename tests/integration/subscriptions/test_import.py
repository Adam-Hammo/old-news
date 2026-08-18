from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from old_news import db
from old_news.config import Settings
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher
from old_news.subscriptions.service import import_opml

SITE = b"""<!doctype html><html><head>
  <link rel="alternate" type="application/rss+xml" href="/discovered.xml">
</head><body>A blog</body></html>"""


HTML = {"Content-Type": "text/html"}
ROUTES = {
    "/blog/": (200, SITE, HTML),
    "/nothing/": (200, b"<html><head></head></html>", HTML),
}


@pytest.fixture
def site(http_server) -> str:
    return http_server(ROUTES)


@pytest.fixture
async def fetcher(settings: Settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


def opml_for(site: str) -> bytes:
    return f"""<?xml version="1.0"?>
    <opml version="2.0"><body>
      <outline text="News" title="News">
        <outline text="Direct" type="rss" xmlUrl="https://direct.example.com/feed.xml"/>
      </outline>
      <outline text="Blog" htmlUrl="{site}/blog/"/>
      <outline text="Feedless" htmlUrl="{site}/nothing/"/>
    </body></opml>""".encode()


async def test_import_adds_feeds_and_discovers_where_needed(clean, site, fetcher):
    result = await import_opml(opml_for(site), fetcher)

    assert result.added == 2
    assert result.undiscoverable == (f"{site}/nothing/",)

    async with db.session() as session:
        urls = set((await session.execute(select(Feed.url))).scalars().all())

    assert urls == {"https://direct.example.com/feed.xml", f"{site}/discovered.xml"}


async def test_folder_titles_become_categories(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        rows = (
            await session.execute(
                select(Feed.url, Subscription.category).join(
                    Subscription, Subscription.feed_id == Feed.id
                )
            )
        ).all()

    assert dict(rows)["https://direct.example.com/feed.xml"] == "News"


async def test_a_discovered_feed_records_the_site_it_came_from(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        feed = (
            await session.execute(select(Feed).where(Feed.url == f"{site}/discovered.xml"))
        ).scalar_one()

    assert feed.site_url == f"{site}/blog/"


async def test_importing_the_same_file_twice_adds_nothing(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    result = await import_opml(opml_for(site), fetcher)

    assert result.added == 0
    assert result.already_present == 2


async def test_every_feed_gets_exactly_one_subscription(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        feeds = len((await session.execute(select(Feed.id))).scalars().all())
        subscriptions = len((await session.execute(select(Subscription.id))).scalars().all())

    assert feeds == subscriptions == 2


async def test_entries_with_nothing_to_poll_are_skipped(clean: None, fetcher, site: str):
    """An OPML file lists what somebody subscribed to, not what can be fetched.
    Exporters put email newsletters and worse in there."""
    opml = b"""<?xml version="1.0"?><opml version="1.0"><body>
      <outline text="A newsletter" xmlUrl="newsletter:0:someone@example.com"/>
      <outline text="An address" xmlUrl="mailto:someone@example.com"/>
      <outline text="Wrong scheme" xmlUrl="ftp://example.com/feed.xml"/>
      <outline text="Real" xmlUrl="https://example.com/feed.xml"/>
    </body></opml>"""

    result = await import_opml(opml, fetcher)

    assert result.added == 1
    assert len(result.unfetchable) == 3

    async with db.session() as session:
        urls = (await session.execute(select(Feed.url))).scalars().all()
    assert list(urls) == ["https://example.com/feed.xml"]
