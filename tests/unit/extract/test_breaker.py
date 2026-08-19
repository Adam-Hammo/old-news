"""Counting a host's refusals. The probe half needs a database and lives in integration."""

import datetime

from old_news.extract.breaker import consecutive_failures

NOW = datetime.datetime(2026, 8, 19, 3, 0, tzinfo=datetime.UTC)


def _rows(*statuses: int) -> list[tuple[int, datetime.datetime]]:
    """Newest first, a minute apart, as the query returns them."""
    return [(status, NOW - datetime.timedelta(minutes=n)) for n, status in enumerate(statuses)]


def test_a_host_answering_normally_has_no_failures():
    assert consecutive_failures(_rows(200, 200, 403)) == (0, None)


def test_failures_are_counted_back_to_the_last_success():
    """Not the whole history. A publisher that broke and recovered starts again."""
    failures, latest = consecutive_failures(_rows(403, 403, 403, 200, 403))

    assert failures == 3
    assert latest == NOW


def test_a_404_is_stepped_over_rather_than_counted():
    """It is about one URL. Counting it would let a handful of dead links close a host
    that is answering everything else."""
    assert consecutive_failures(_rows(404, 404, 404))[0] == 0
    assert consecutive_failures(_rows(403, 404, 403))[0] == 2


def test_a_410_does_not_close_a_host_either():
    assert consecutive_failures(_rows(410, 410))[0] == 0


def test_a_transport_failure_counts():
    """Status 0 is DNS or a refused connection, which is the host, not the page."""
    assert consecutive_failures(_rows(0, 0))[0] == 2


def test_a_host_never_tried_has_nothing_to_say():
    assert consecutive_failures([]) == (0, None)
