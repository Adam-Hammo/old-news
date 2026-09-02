"""The production entry point: a timer defers polls, a worker runs them."""

import pytest
from sqlalchemy import text

from old_news import db
from old_news.db import Feed, FeedPoll, PollOutcome, Subscription
from old_news.politeness import resolve
from old_news.tasks.ingest import schedule_polls
from old_news.tasks.maintenance import heartbeat


async def _due_feed(url: str, *, active: bool = True, gone: bool = False) -> Feed:
    async with db.session() as session:
        feed = Feed(url=url, host_id=await resolve(session, url))
        session.add(feed)
        await session.flush()
        session.add(Subscription(feed_id=feed.id, active=active))
        if gone:
            # A 410 is the publisher withdrawing the feed, and the only answer that
            # stops the polling on its own.
            session.add(
                FeedPoll(feed_id=feed.id, outcome=PollOutcome.FAILED, status=410, error="gone")
            )
    return feed


async def _queued() -> list[tuple]:
    async with db.session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT queueing_lock, args, lock, scheduled_at "
                        "FROM procrastinate_jobs WHERE task_name = 'poll_feed' ORDER BY id"
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
    assert queued[0][0] == f"feed:{feed.id}"
    assert queued[0][1]["feed_id"] == str(feed.id)
    assert queued[0][2] == "host:due.example.com"
    # First visit to a host waits for nothing.
    assert queued[0][3] is None


async def test_unsubscribed_and_withdrawn_feeds_are_skipped(
    no_jobs: None, queue_app, settings, monkeypatch
):
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    await _due_feed("https://dropped.example.com/feed.xml", active=False)
    await _due_feed("https://broken.example.com/feed.xml", gone=True)

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    assert await _queued() == []


async def test_feeds_from_one_publisher_serialise_behind_a_host_lock(
    no_jobs: None, queue_app, settings, monkeypatch
):
    """The whole of politeness: Postgres serialises, and `fetch/` knows nothing."""
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    for path in ("uk", "world", "sport"):
        await _due_feed(f"https://www.theguardian.com/{path}/rss")
    await _due_feed("https://www.bbc.co.uk/news/rss.xml")

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    queued = await _queued()
    locks = [row[2] for row in queued]

    assert locks.count("host:theguardian.com") == 3
    assert locks.count("host:bbc.co.uk") == 1


async def test_a_publishers_feeds_are_spaced_out_and_other_hosts_are_not(
    no_jobs: None, queue_app, settings, monkeypatch
):
    """The lock alone would run them back-to-back as fast as each poll finishes."""
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    gap = settings.http.min_host_interval_seconds
    assert gap > 0

    for path in ("uk", "world", "sport"):
        await _due_feed(f"https://www.theguardian.com/{path}/rss")
    await _due_feed("https://www.bbc.co.uk/news/rss.xml")

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    queued = await _queued()
    by_host: dict[str, list] = {}
    for row in queued:
        by_host.setdefault(row[2], []).append(row[3])

    guardian = by_host["host:theguardian.com"]
    assert len(guardian) == 3
    # The first visit waits for nothing; each one after it is held back by
    # another gap. Approximate because every defer stamps its own now().
    assert guardian[0] is None
    assert (guardian[2] - guardian[1]).total_seconds() == pytest.approx(gap, abs=1.0)

    # A quiet publisher is never made to wait for a busy one.
    assert by_host["host:bbc.co.uk"] == [None]


async def test_postgres_hands_out_one_job_per_host_at_a_time(no_jobs: None, queue_app):
    """The invariant politeness rests on, asserted against a real Postgres."""
    manager = queue_app.job_manager

    async with queue_app.open_async():
        for note in ("first", "second"):
            await heartbeat.configure(lock="host:theguardian.com").defer_async(note=note)
        await heartbeat.configure(lock="host:bbc.co.uk").defer_async(note="other")

        worker_id = await manager.register_worker()
        # No completion in between, so the first job stays `doing`.
        claimed = [await manager.fetch_job(None, worker_id) for _ in range(3)]

    locks = [job.lock for job in claimed if job is not None]

    assert locks == ["host:theguardian.com", "host:bbc.co.uk"]
    assert claimed[2] is None


async def test_a_feed_already_queued_does_not_kill_the_sweep(
    no_jobs: None, queue_app, settings, monkeypatch
):
    """An unhandled lock collision used to end the sweep and leave the rest undeferred."""
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    for path in ("uk", "world", "sport"):
        await _due_feed(f"https://www.theguardian.com/{path}/rss")

    async with queue_app.open_async():
        await schedule_polls(timestamp=0)
        first_pass = len(await _queued())
        # Nothing has run, so every lock is still held.
        await schedule_polls(timestamp=60)

    assert first_pass == 3
    # The second sweep skipped all three rather than failing on the first.
    assert len(await _queued()) == 3
