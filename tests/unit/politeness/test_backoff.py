"""The shared retry arithmetic. That its SQL spelling agrees lives in integration."""

import datetime

from old_news.politeness import backoff

POLICY = backoff.Policy(minimum_seconds=300, maximum_seconds=86400, factor=2.0, max_failures=6)


def test_waits_lengthen_with_each_failure():
    waits = [backoff.interval(POLICY, failures=n) for n in range(4)]

    assert waits == [300, 600, 1200, 2400]


def test_waits_are_held_inside_the_bounds():
    assert backoff.interval(POLICY, failures=0, base_seconds=1) == POLICY.minimum_seconds
    assert backoff.interval(POLICY, failures=99) == POLICY.maximum_seconds


def test_asking_stops_at_the_failure_ceiling():
    assert not backoff.exhausted(POLICY, failures=POLICY.max_failures - 1)
    assert backoff.exhausted(POLICY, failures=POLICY.max_failures)


def test_retry_at_is_the_interval_from_now():
    now = datetime.datetime(2026, 8, 19, 3, 0, tzinfo=datetime.UTC)

    assert backoff.retry_at(now, POLICY, failures=1) == now + datetime.timedelta(seconds=600)
