"""Filing, dropping and listing what we follow — what a settings screen does."""

import uuid
from collections.abc import AsyncIterator

import pytest

from old_news.config import Settings
from old_news.db import Tier
from old_news.fetch import Fetcher
from old_news.subscriptions.service import (
    NoFeedFound,
    UnpollableUrl,
    add,
    drop,
    listing,
    refile,
    subscribe,
)

FEED_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel>
  <title>A blog</title></channel></rss>"""
SITE_HTML = b"""<!doctype html><html><head>
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body>A blog</body></html>"""


async def _file(feed_id, *, category="", tier=Tier.WIRE, expires_after_seconds=None) -> bool:
    """`refile` takes the whole filing; most of these tests are only about the section."""
    return await refile(
        feed_id, category=category, tier=tier, expires_after_seconds=expires_after_seconds
    )


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


async def test_a_feed_can_be_moved_to_another_section(clean: None):
    feed = await add(FEED, title="Example", category="Technology")
    assert feed is not None

    assert await _file(feed.id, category="Science") is True

    assert [f.category for f in await listing()] == ["Science"]


async def test_a_feed_can_be_unfiled_again(clean: None):
    feed = await add(FEED, category="Technology")
    assert feed is not None

    assert await _file(feed.id, category="") is True

    assert [f.category for f in await listing()] == [""]


async def test_filing_something_we_do_not_follow_says_so(clean: None):
    assert await _file(uuid.uuid4(), category="Science") is False


async def test_filing_a_feed_we_dropped_says_so(clean: None):
    feed = await add(FEED)
    assert feed is not None
    await drop(feed.id)

    assert await _file(feed.id, category="Science") is False


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


async def test_the_tier_and_the_window_are_set_together_with_the_section(clean: None):
    """One call, because a partial filing cannot say "never expires" and "unchanged"."""
    feed = await add(FEED, title="Example", category="Technology")
    assert feed is not None

    assert await _file(feed.id, category="Essays", tier=Tier.KINDLE, expires_after_seconds=1209600)

    filed = (await listing())[0]
    assert (filed.category, filed.tier, filed.expires_after_seconds) == (
        "Essays",
        Tier.KINDLE,
        1209600,
    )


async def test_a_window_can_be_taken_off_again(clean: None):
    """Null is the feed nothing ages out of, which a number cannot express."""
    feed = await add(FEED)
    assert feed is not None
    await _file(feed.id, expires_after_seconds=3600)

    await _file(feed.id, expires_after_seconds=None)

    assert (await listing())[0].expires_after_seconds is None


async def test_a_listed_feed_carries_its_tier_and_window(clean: None):
    feed = await add(FEED)
    assert feed is not None

    listed = (await listing())[0]

    assert (listed.tier, listed.expires_after_seconds) == (Tier.WIRE, None)
