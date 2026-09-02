import datetime

import pytest

from old_news.config import IngestSettings
from old_news.fetch import Response
from old_news.ingest.schedule import next_interval, next_poll_at
from old_news.ingest.service import _retry_after


@pytest.fixture
def settings() -> IngestSettings:
    return IngestSettings()


def test_a_healthy_feed_that_published_is_visited_sooner(settings):
    interval = next_interval(settings, current_seconds=1800, new_items=3)

    assert interval == 900


def test_a_quiet_feed_drifts_later(settings):
    interval = next_interval(settings, current_seconds=1800, new_items=0)

    assert interval == 2700


def test_backoff_is_exponential_in_failures(settings):
    intervals = [next_interval(settings, failures=n) for n in (1, 2, 3)]

    assert intervals == sorted(intervals)
    assert intervals[1] == intervals[0] * 2


def test_intervals_are_clamped_to_the_configured_bounds(settings):
    assert next_interval(settings, current_seconds=1, new_items=1) == settings.min_interval_seconds
    assert next_interval(settings, failures=50) == settings.max_interval_seconds


def test_feed_ttl_raises_the_floor(settings):
    """<ttl> asks to be polled less often, so it may only lengthen the wait."""
    interval = next_interval(settings, current_seconds=1800, new_items=5, ttl_seconds=3600)

    assert interval == 3600


def test_feed_ttl_never_shortens_the_wait(settings):
    interval = next_interval(settings, current_seconds=1800, new_items=0, ttl_seconds=60)

    assert interval == 2700


def test_a_ttl_beyond_our_ceiling_is_still_honoured(settings):
    """Our maximum is a policy; the publisher's request outranks it."""
    two_days = 172800

    assert next_interval(settings, failures=0, ttl_seconds=two_days) == two_days


def test_ttl_can_be_ignored_by_configuration():
    settings = IngestSettings(honour_feed_ttl=False)

    assert next_interval(settings, current_seconds=1800, new_items=0, ttl_seconds=99999) == 2700


def test_next_poll_at_is_now_plus_the_interval(settings):
    now = datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC)

    assert next_poll_at(
        now, settings, current_seconds=1800, new_items=0
    ) == now + datetime.timedelta(seconds=2700)


def test_a_retry_after_beyond_our_ceiling_is_capped(settings):
    """A server sending 999999999 would otherwise park the feed for decades."""
    response = Response(status=503, url="https://x", body=b"", headers={"Retry-After": "999999999"})

    assert _retry_after(response, settings) == settings.max_interval_seconds
