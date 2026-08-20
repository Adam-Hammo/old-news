"""The shared retry arithmetic. That its SQL spelling agrees lives in integration."""

from old_news.politeness import backoff

POLICY = backoff.Policy(minimum_seconds=300, maximum_seconds=86400, factor=2.0, max_failures=6)


def test_waits_lengthen_with_each_failure():
    waits = [backoff.interval(POLICY, failures=n) for n in range(4)]

    assert waits == [300, 600, 1200, 2400]


def test_waits_are_held_inside_the_bounds():
    assert backoff.interval(POLICY, failures=0, base_seconds=1) == POLICY.minimum_seconds
    assert backoff.interval(POLICY, failures=99) == POLICY.maximum_seconds
