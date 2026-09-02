import pytest

from old_news.fetch import fetchable
from old_news.politeness import host_lock, host_of, with_www


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


def test_the_www_name_is_the_same_url_under_a_different_host():
    """theclimatebrink.com serves its feed from `www` and links its articles at an apex
    with no DNS record at all."""
    assert (
        with_www("https://theclimatebrink.com/p/hot-days")
        == "https://www.theclimatebrink.com/p/hot-days"
    )


def test_a_url_already_on_www_is_left_alone():
    assert with_www("https://www.bbc.co.uk/news") == "https://www.bbc.co.uk/news"


def test_something_that_is_not_a_url_is_left_alone():
    assert with_www("newsletter:0:someone@example.com") == "newsletter:0:someone@example.com"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://EXAMPLE.com/x", "https://www.EXAMPLE.com/x"),
        ("https://münchen.de/artikel", "https://www.münchen.de/artikel"),
        ("https://example.com:8443/a", "https://www.example.com:8443/a"),
        ("https://user:pass@example.com/x", "https://user:pass@www.example.com/x"),
    ],
)
def test_the_host_is_replaced_in_the_netloc_and_not_in_the_string(url: str, expected: str):
    """The parsed host is lowercased and punycoded. Replacing it as a substring finds
    nothing in either of the first two and silently returns the URL unchanged."""
    assert with_www(url) == expected
