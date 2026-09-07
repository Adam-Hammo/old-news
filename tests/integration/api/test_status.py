"""The settings screen's other half: what the box is doing, and what it is set to."""

import datetime

from sqlalchemy import select

from old_news import db
from old_news.config import Settings
from old_news.config.visible import REDACTED, sections
from old_news.db import Feed, FeedPoll, PollOutcome, RobotsPolicy
from old_news.subscriptions.service import add

FEED = "https://example.com/feed.xml"


@db.transactional
async def _polled(session, feed_id, *, outcome: str, status: int, error: str = "") -> None:
    session.add(FeedPoll(feed_id=feed_id, outcome=outcome, status=status, error=error))


@db.transactional
async def _robots(session, feed_id, *, delay: float, status: int) -> None:
    host_id = await session.scalar(select(Feed.host_id).where(Feed.id == feed_id))
    session.add(RobotsPolicy(host_id=host_id, crawl_delay_seconds=delay, status=status))


async def test_polling_carries_the_last_visit_as_it_went(served):
    feed = await add(FEED, title="Example", category="Technology")
    assert feed is not None
    await _polled(feed.id, outcome=PollOutcome.FAILED, status=503, error="upstream said no")
    client = await served()

    row = (await client.get("/status/polling")).json()[0]

    assert (row["title"], row["outcome"], row["status"], row["error"]) == (
        "Example",
        "failed",
        503,
        "upstream said no",
    )


# A screen that lists forty feeds is only worth opening if the broken ones are at the top.
async def test_the_feeds_in_trouble_come_first(served):
    healthy = await add(FEED, title="Healthy")
    broken = await add("https://broken.example.com/feed.xml", title="Broken")
    assert healthy is not None and broken is not None
    await _polled(healthy.id, outcome=PollOutcome.OK, status=200)
    for _ in range(3):
        await _polled(broken.id, outcome=PollOutcome.FAILED, status=500)
    client = await served()

    rows = (await client.get("/status/polling")).json()

    assert [(r["title"], r["consecutive_failures"]) for r in rows] == [
        ("Broken", 3),
        ("Healthy", 0),
    ]


async def test_a_dropped_feed_is_not_something_we_are_polling(served):
    feed = await add(FEED, title="Example")
    assert feed is not None
    client = await served()
    await client.delete(f"/subscriptions/{feed.id}")

    assert (await client.get("/status/polling")).json() == []


async def test_a_publisher_carries_what_its_robots_asked_for(served):
    feed = await add(FEED, title="Example")
    assert feed is not None
    await _robots(feed.id, delay=12.5, status=200)
    client = await served()

    row = (await client.get("/status/publishers")).json()[0]

    assert (row["name"], row["feeds"], row["crawl_delay_seconds"], row["robots_status"]) == (
        "example.com",
        1,
        12.5,
        200,
    )


# A host nobody has fetched robots for is not a host with a delay of zero.
async def test_a_publisher_that_asked_for_nothing_says_so(served):
    assert await add(FEED, title="Example") is not None
    client = await served()

    row = (await client.get("/status/publishers")).json()[0]

    assert row["crawl_delay_seconds"] is None
    assert row["robots_status"] == 0


async def test_the_config_lists_every_section(served):
    client = await served()

    named = [section["name"] for section in (await client.get("/status/config")).json()]

    assert {"ingest", "robots", "http", "extract", "kindle"} <= set(named)


SENTINEL = "SUPERSECRET-DO-NOT-SHOW-THIS"


def test_no_credential_can_reach_the_screen():
    """Every credential is a `SecretStr`, which renders itself as asterisks. This is the
    check that a field added as a plain string does not get through anyway."""
    settings = Settings(
        database={"url": f"postgres://u:{SENTINEL}@localhost/x"},
        telemetry={"logfire_token": SENTINEL},
        admin={"password_hash": SENTINEL, "session_secret": SENTINEL},
        kindle={"smtp_password": SENTINEL, "smtp_user": "someone@example.com"},
    )

    shown = [setting for section in sections(settings) for setting in section.settings]

    assert SENTINEL not in " ".join(setting.value for setting in shown)
    assert {"url", "logfire_token", "password_hash", "smtp_password"} <= {
        setting.name for setting in shown if setting.value == REDACTED
    }


def test_a_setting_that_is_not_a_credential_is_shown():
    """Redacting everything would be safe and useless."""
    settings = Settings(ingest={"default_interval_seconds": 999})

    ingest = next(section for section in sections(settings) if section.name == "ingest")

    assert ("default_interval_seconds", "999") in [(s.name, s.value) for s in ingest.settings]


def test_a_window_reads_as_a_duration_not_a_python_repr():
    settings = Settings()

    robots = next(section for section in sections(settings) if section.name == "robots")

    assert ("ttl_seconds", str(int(datetime.timedelta(days=1).total_seconds()))) in [
        (s.name, s.value) for s in robots.settings
    ]
