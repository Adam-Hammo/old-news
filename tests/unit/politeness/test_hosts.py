import pytest

from old_news.fetch import fetchable
from old_news.politeness import host_lock, host_of


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.theguardian.com/uk/rss", "theguardian.com"),
        # An IDN host, both ways round. urlsplit returned these as two different
        # publishers, which let one of them be polled twice as hard as intended.
        ("https://münchen.de/feed.xml", "xn--mnchen-3ya.de"),
        ("https://xn--mnchen-3ya.de/feed.xml", "xn--mnchen-3ya.de"),
        ("https://user:pw@example.com/feed.xml", "example.com"),
        ("https://theguardian.com/world/rss", "theguardian.com"),
        ("https://WWW.Theguardian.COM/uk/rss", "theguardian.com"),
        ("https://feeds.theguardian.com/rss", "feeds.theguardian.com"),
        ("https://example.com:8443/feed.xml?key=secret", "example.com"),
    ],
)
def test_host_of(url, expected):
    assert host_of(url) == expected


def test_the_same_publisher_spelled_two_ways_is_one_group():
    """The regression that matters: two spellings, one lock, one crawl delay."""
    unicode_form = host_of("https://münchen.de/feed.xml")
    punycode_form = host_of("https://xn--mnchen-3ya.de/feed.xml")

    assert unicode_form == punycode_form
    assert host_lock(unicode_form) == host_lock(punycode_form)


@pytest.mark.parametrize(
    "url",
    ["not-a-url", "mailto:someone@example.com", "ftp://example.com/f.xml", "https://", ""],
)
def test_anything_unfetchable_has_no_host_and_no_lock(url):
    assert host_of(url) == ""
    assert host_lock(host_of(url)) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/feed.xml",
        "http://example.com/feed.xml",
        "https://münchen.de/feed.xml",
        "mailto:someone@example.com",
        "ftp://example.com/feed.xml",
        "not-a-url",
        "",
    ],
)
def test_having_a_host_and_being_fetchable_are_the_same_question(url):
    """Both go through `fetch.http_url`. If they ever disagree, a feed is either
    polled with no politeness group or grouped but never fetched."""
    assert bool(host_of(url)) is fetchable(url)


def test_feeds_from_one_publisher_share_a_lock():
    hosts = [host_of(u) for u in ("https://www.bbc.co.uk/a/rss", "https://bbc.co.uk/b/rss")]

    assert len(set(map(host_lock, hosts))) == 1
