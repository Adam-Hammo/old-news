import datetime
from pathlib import Path

import pytest

from old_news.ingest.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"
FEED_URL = "https://www.example.com/feed.xml"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def rss():
    return parse(fixture("rss2.xml"), url=FEED_URL)


def test_channel_metadata(rss):
    assert rss.title == "The Example"
    assert rss.description == "A feed for testing"
    assert rss.language == "en-GB"
    assert rss.platform == "WordPress 6.4"
    assert rss.site_url == "https://www.example.com/"
    assert rss.icon_url == "https://www.example.com/icon.png"
    assert rss.hub_url == "https://pubsubhubbub.example.com/"
    assert rss.categories == ("News",)


def test_ttl_prefers_the_explicit_element_in_minutes(rss):
    assert rss.ttl_seconds == 45 * 60


def test_update_period_is_divided_by_frequency():
    """sy:updatePeriod hourly with frequency 2 means twice an hour."""
    body = fixture("rss2.xml").replace(b"<ttl>45</ttl>", b"")

    assert parse(body, url=FEED_URL).ttl_seconds == 1800


def test_relative_links_resolve_against_the_channel_link(rss):
    assert rss.items[0].url == "https://www.example.com/news/first?utm_source=rss&utm_medium=feed"
    assert rss.items[0].comments_url == "https://www.example.com/news/first#comments"


def test_canonical_url_strips_tracking(rss):
    assert rss.items[0].canonical_url == "https://example.com/news/first"


def test_content_is_preferred_over_summary(rss):
    assert rss.items[0].content == "<p>Full body</p>"
    assert rss.items[0].summary == "A summary"


def test_tags_and_enclosures(rss):
    assert rss.items[0].tags == ("Politics", "UK")
    assert rss.items[0].enclosures == (
        {"url": "https://www.example.com/audio/first.mp3", "type": "audio/mpeg", "length": "12345"},
    )


def test_dates_are_timezone_aware(rss):
    assert rss.items[0].published_at == datetime.datetime(2026, 8, 3, 9, 0, tzinfo=datetime.UTC)


def test_missing_guid_is_left_empty_for_the_caller_to_resolve(rss):
    assert rss.items[0].guid == "tag:example.com,2026:1"
    assert rss.items[1].guid == ""


def test_atom_parses_the_same_shape():
    parsed = parse(fixture("atom.xml"), url="https://atom.example.com/feed")

    assert parsed.title == "Atom Example"
    assert parsed.description == "Subtitle here"
    assert parsed.items[0].content == "<p>Atom body</p>"
    assert parsed.items[0].guid == "urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a"


def test_malformed_is_recorded_not_rejected():
    """Much of the web's RSS sets bozo and parses fine anyway."""
    parsed = parse(fixture("malformed.xml"), url="https://broken.example.com/feed")

    assert parsed.items
    assert parsed.ok is True
    assert parsed.note


def test_undated_entries_survive():
    parsed = parse(fixture("undated.xml"), url="https://undated.example.com/feed")

    assert len(parsed.items) == 2
    assert parsed.items[0].published_at is None


def test_empty_document_is_reported_as_empty():
    parsed = parse(b"", url=FEED_URL)

    assert parsed.empty
