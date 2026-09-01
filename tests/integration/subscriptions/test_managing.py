"""Filing, dropping and listing what we follow — what a settings screen does."""

import uuid
from collections.abc import AsyncIterator

import pytest

from old_news.config import Settings
from old_news.fetch import Fetcher
from old_news.subscriptions.service import (
    NoFeedFound,
    UnpollableUrl,
    add,
    drop,
    listing,
    refile,
    subscribe,
    unsubscribe,
)

FEED_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel>
  <title>A blog</title></channel></rss>"""
SITE_HTML = b"""<!doctype html><html><head>
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body>A blog</body></html>"""

ROUTES = {
    "/blog/": (200, SITE_HTML, {"Content-Type": "text/html"}),
    "/feed.xml": (200, FEED_XML, {"Content-Type": "application/rss+xml"}),
    "/bare/": (200, b"<html><head></head></html>", {"Content-Type": "text/html"}),
}


@pytest.fixture
def site(http_server) -> str:
    return http_server(ROUTES)


@pytest.fixture
async def fetcher(settings: Settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


FEED = "https://example.com/feed.xml"
OTHER = "https://other.example.com/feed.xml"


async def test_what_we_follow_comes_back_filed(clean: None):
    await add(FEED, title="Example", category="Technology")
    await add(OTHER, title="Other", category="Science")

    following = await listing()

    assert [(f.title, f.category) for f in following] == [
        ("Other", "Science"),
        ("Example", "Technology"),
    ]


async def test_a_feed_we_dropped_is_not_in_the_listing(clean: None):
    feed = await add(FEED, title="Example")
    assert feed is not None

    assert await drop(feed.id) is True

    assert await listing() == ()


# The archive outlives the subscription, so dropping is not deleting.
async def test_dropping_by_id_and_by_url_are_the_same_thing(clean: None):
    feed = await add(FEED)
    assert feed is not None

    assert await drop(feed.id) is True
    assert await drop(feed.id) is False
    assert await unsubscribe(FEED) is False


async def test_a_feed_can_be_moved_to_another_section(clean: None):
    feed = await add(FEED, title="Example", category="Technology")
    assert feed is not None

    assert await refile(feed.id, "Science") is True

    assert [f.category for f in await listing()] == ["Science"]


async def test_a_feed_can_be_unfiled_again(clean: None):
    feed = await add(FEED, category="Technology")
    assert feed is not None

    assert await refile(feed.id, "") is True

    assert [f.category for f in await listing()] == [""]


async def test_filing_something_we_do_not_follow_says_so(clean: None):
    assert await refile(uuid.uuid4(), "Science") is False


async def test_filing_a_feed_we_dropped_says_so(clean: None):
    feed = await add(FEED)
    assert feed is not None
    await drop(feed.id)

    assert await refile(feed.id, "Science") is False


async def test_a_pasted_page_is_followed_by_the_feed_it_names(clean: None, site, fetcher):
    """The capability the roadmap said had no interface: subscribing from a pasted URL."""
    feed = await subscribe(f"{site}/blog/", fetcher, category="Technology")

    assert feed is not None and feed.url == f"{site}/feed.xml"
    following = await listing()
    assert [(f.url, f.category, f.site_url) for f in following] == [
        (f"{site}/feed.xml", "Technology", f"{site}/blog/")
    ]


async def test_a_pasted_feed_is_followed_as_itself(clean: None, site, fetcher):
    feed = await subscribe(f"{site}/feed.xml", fetcher)

    assert feed is not None and feed.url == f"{site}/feed.xml"
    # Nothing to record: the address pasted is the feed, not a page in front of it.
    assert [f.site_url for f in await listing()] == [""]


async def test_a_page_naming_no_feed_says_so(clean: None, site, fetcher):
    with pytest.raises(NoFeedFound):
        await subscribe(f"{site}/bare/", fetcher)


async def test_following_the_same_thing_twice_is_not_an_error_but_is_not_a_change(
    clean: None, site, fetcher
):
    assert await subscribe(f"{site}/blog/", fetcher) is not None

    assert await subscribe(f"{site}/blog/", fetcher) is None
    assert len(await listing()) == 1


async def test_something_that_is_not_a_pollable_address_is_refused(clean: None, fetcher):
    with pytest.raises(UnpollableUrl):
        await subscribe("mailto:someone@example.com", fetcher)
