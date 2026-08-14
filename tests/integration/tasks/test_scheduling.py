"""The production entry point: a timer defers polls, a worker runs them."""

import pytest
from sqlalchemy import text

from old_news import db
from old_news.db import Feed, Subscription
from old_news.tasks.ingest import schedule_polls


@pytest.fixture
async def no_jobs(clean: None) -> None:
    """`clean` truncates feeds; the queue is a separate schema procrastinate owns."""
    async with db.session() as session:
        await session.execute(text("TRUNCATE procrastinate_jobs CASCADE"))


async def _due_feed(url: str, *, active: bool = True, suspended: bool = False) -> Feed:
    async with db.session() as session:
        feed = Feed(url=url, suspended=suspended)
        session.add(feed)
        await session.flush()
        session.add(Subscription(feed_id=feed.id, active=active))
    return feed


async def _queued() -> list[tuple]:
    async with db.session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT queueing_lock, args FROM procrastinate_jobs "
                        "WHERE task_name = 'poll_feed'"
                    )
                )
            ).all()
        )


async def test_a_due_feed_is_deferred_once(no_jobs: None, queue_app, settings, monkeypatch):
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    feed = await _due_feed("https://due.example.com/feed.xml")

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    queued = await _queued()

    assert len(queued) == 1
    # One poll per feed in flight: a feed slower than its interval would
    # otherwise stack up behind itself forever.
    assert queued[0][0] == f"feed:{feed.id}"
    # An identifier, never a URL — procrastinate logs kwargs at INFO.
    assert queued[0][1]["feed_id"] == str(feed.id)


async def test_unsubscribed_and_suspended_feeds_are_skipped(
    no_jobs: None, queue_app, settings, monkeypatch
):
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    await _due_feed("https://dropped.example.com/feed.xml", active=False)
    await _due_feed("https://broken.example.com/feed.xml", suspended=True)

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    assert await _queued() == []
