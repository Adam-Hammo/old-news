"""The shared retry arithmetic, including that both spellings of it agree."""

import datetime

import pytest
from sqlalchemy import column, select
from sqlalchemy.dialects import postgresql

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


@pytest.mark.parametrize("failures", range(8))
def test_the_sql_form_computes_what_the_python_form_does(failures: int):
    """`due_at` exists so a sweep can order and limit by a backoff. Two spellings of one
    formula drift silently, so the numbers are compared rather than the code trusted."""
    compiled = str(
        select(backoff.due_at(column("fetched_at"), column("failures"), POLICY)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    seconds = backoff.interval(POLICY, failures=failures)

    assert f"least(greatest({POLICY.minimum_seconds} * power" in compiled
    assert seconds == min(
        max(POLICY.minimum_seconds * POLICY.factor**failures, POLICY.minimum_seconds),
        POLICY.maximum_seconds,
    )


def test_retry_at_is_the_interval_from_now():
    now = datetime.datetime(2026, 8, 19, 3, 0, tzinfo=datetime.UTC)

    assert backoff.retry_at(now, POLICY, failures=1) == now + datetime.timedelta(seconds=600)
