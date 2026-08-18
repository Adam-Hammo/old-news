"""The process-wide client. Its whole purpose is that you get the same one back."""

import pytest

from old_news import fetch
from old_news.config.http import HttpSettings


@pytest.fixture(autouse=True)
async def clean_client():
    yield
    await fetch.dispose()


async def test_the_same_client_comes_back_every_time():
    """A new Fetcher per call would be a new connection pool per call, which is the
    thing this exists to stop."""
    fetch.configure(HttpSettings())

    assert fetch.client() is fetch.client()


async def test_asking_before_configuring_says_so():
    await fetch.dispose()

    with pytest.raises(RuntimeError, match="not configured"):
        fetch.client()


async def test_reconfiguring_replaces_the_client():
    """Otherwise a second app in one process would keep the first one's settings."""
    fetch.configure(HttpSettings())
    first = fetch.client()

    fetch.configure(HttpSettings(timeout_seconds=1.0))

    assert fetch.client() is not first


async def test_dispose_is_safe_when_nothing_was_built():
    fetch.configure(HttpSettings())

    await fetch.dispose()
    await fetch.dispose()
