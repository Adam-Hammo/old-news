import pytest

from old_news.fetch import fetchable


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/feed.xml",
        "http://example.com/feed.xml",
        "HTTPS://Example.com/feed.xml",
        "https://example.com:8443/feed.xml?key=secret",
    ],
)
def test_a_web_url_is_fetchable(url):
    assert fetchable(url)


@pytest.mark.parametrize(
    "url",
    [
        "newsletter:0:someone@example.com",
        "mailto:someone@example.com",
        "ftp://example.com/feed.xml",
        "example.com/feed.xml",
        "https://",
        "",
        "   ",
    ],
)
def test_anything_without_a_host_over_http_is_not(url):
    assert not fetchable(url)
