"""The robots.txt sweep: which hosts get asked, and how politely."""

import datetime

import pytest
from sqlalchemy import text

from old_news import db
from old_news.db import Feed, RobotsPolicy, Subscription
from old_news.politeness import ensure, resolve
from old_news.tasks.ingest import schedule_polls
from old_news.tasks.robots import schedule_robots


async def _subscribed(url: str) -> Feed:
    async with db.session() as session:
        feed = Feed(url=url, host_id=await resolve(session, url))
        session.add(feed)
        await session.flush()
        session.add(Subscription(feed_id=feed.id, active=True))
    return feed


async def _policy(host: str, *, crawl_delay: float | None, expires_in_hours: float) -> None:
    now = datetime.datetime.now(datetime.UTC)
    async with db.session() as session:
        session.add(
            RobotsPolicy(
                host_id=await ensure(session, host),
                body=f"User-agent: *\nCrawl-delay: {crawl_delay}" if crawl_delay else "",
                status=200,
                crawl_delay_seconds=crawl_delay,
                fetched_at=now,
                expires_at=now + datetime.timedelta(hours=expires_in_hours),
            )
        )


async def _jobs(task_name: str) -> list[tuple]:
    async with db.session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT args, lock, queueing_lock, scheduled_at FROM procrastinate_jobs "
                        "WHERE task_name = :task ORDER BY id"
                    ),
                    {"task": task_name},
                )
            ).all()
        )


async def test_every_subscribed_host_is_asked_once(
    no_jobs: None, no_policies: None, queue_app, settings, monkeypatch
):
    monkeypatch.setattr("old_news.tasks.robots.get_settings", lambda: settings)
    for path in ("uk", "world"):
        await _subscribed(f"https://www.theguardian.com/{path}/rss")
    await _subscribed("https://www.bbc.co.uk/news/rss.xml")

    async with queue_app.open_async():
        await schedule_robots(timestamp=0)

    jobs = await _jobs("refresh_robots")
    hosts = sorted(job[0]["host"] for job in jobs)

    # Two Guardian feeds, one robots.txt.
    assert hosts == ["bbc.co.uk", "theguardian.com"]


async def test_a_robots_fetch_queues_behind_that_hosts_other_traffic(
    no_jobs: None, no_policies: None, queue_app, settings, monkeypatch
):
    """Asking for the rules is itself a request, so it takes the same host lock."""
    monkeypatch.setattr("old_news.tasks.robots.get_settings", lambda: settings)
    await _subscribed("https://www.theguardian.com/uk/rss")

    async with queue_app.open_async():
        await schedule_robots(timestamp=0)

    jobs = await _jobs("refresh_robots")

    assert jobs[0][1] == "host:theguardian.com"
    assert jobs[0][2] == "robots:theguardian.com"


async def test_a_host_with_current_rules_is_not_asked_again(
    no_jobs: None, no_policies: None, queue_app, settings, monkeypatch
):
    monkeypatch.setattr("old_news.tasks.robots.get_settings", lambda: settings)
    await _subscribed("https://www.theguardian.com/uk/rss")
    await _policy("theguardian.com", crawl_delay=None, expires_in_hours=6)

    async with queue_app.open_async():
        await schedule_robots(timestamp=0)

    assert await _jobs("refresh_robots") == []


async def test_an_expired_policy_is_asked_again(
    no_jobs: None, no_policies: None, queue_app, settings, monkeypatch
):
    monkeypatch.setattr("old_news.tasks.robots.get_settings", lambda: settings)
    await _subscribed("https://www.theguardian.com/uk/rss")
    await _policy("theguardian.com", crawl_delay=None, expires_in_hours=-1)

    async with queue_app.open_async():
        await schedule_robots(timestamp=0)

    assert len(await _jobs("refresh_robots")) == 1


async def test_a_hosts_crawl_delay_spaces_out_its_polls(
    no_jobs: None, no_policies: None, queue_app, settings, monkeypatch
):
    """`Crawl-delay` falls out as `schedule_in` — the same mechanism, no new state."""
    monkeypatch.setattr("old_news.tasks.ingest.get_settings", lambda: settings)
    crawl_delay = settings.http.min_host_interval_seconds * 6
    for path in ("uk", "world"):
        await _subscribed(f"https://www.theguardian.com/{path}/rss")
    await _policy("theguardian.com", crawl_delay=crawl_delay, expires_in_hours=6)

    before = datetime.datetime.now(datetime.UTC)
    async with queue_app.open_async():
        await schedule_polls(timestamp=0)

    scheduled = [job[3] for job in await _jobs("poll_feed")]

    assert len(scheduled) == 2
    # The first visit waits for nothing; the second waits the publisher's own delay
    # rather than our shorter default.
    assert scheduled[0] is None
    assert (scheduled[1] - before).total_seconds() == pytest.approx(crawl_delay, abs=1.0)
