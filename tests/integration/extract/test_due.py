"""What is worth fetching. Every condition in `due_captures`, one at a time."""

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import Dimension, PageCapture, RobotsPolicy, RuleSource, TrainingRule
from old_news.politeness import ensure

SETTINGS = ExtractSettings()


@db.transactional
async def _capture(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    status: int,
    ago: datetime.timedelta = datetime.timedelta(0),
    times: int = 1,
) -> None:
    host_id = await ensure(session, "loopback.example.com")
    for _ in range(times):
        session.add(
            PageCapture(
                item_version_id=version_id,
                host_id=host_id,
                url="https://loopback.example.com/a",
                status=status,
                body_hash=b"0" * 32,
                fetched_at=datetime.datetime.now(datetime.UTC) - ago,
            )
        )
    await session.flush()


@db.transactional
async def _rule(session: AsyncSession, **values) -> None:
    session.add(TrainingRule(source=RuleSource.HAND, blocks=True, **values))
    await session.flush()


@db.transactional
async def _rules_read(session: AsyncSession, host: str = "loopback.example.com") -> None:
    """A host whose robots.txt has been asked for. Nothing is fetched from one that
    has not been, so most of these tests need it."""
    session.add(
        RobotsPolicy(
            host_id=await ensure(session, host),
            body="",
            status=200,
            expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )
    )
    await session.flush()


async def _due_urls() -> list[str]:
    return sorted(item.url for item in await extract.due_captures(SETTINGS, limit=50))


async def test_a_first_version_is_due_immediately(clean: None, feed_id, article):
    """Not settled, and due anyway. This is what guarantees every article has something,
    and what catches a publisher who pulls a mistake inside the window."""
    await _rules_read()
    await article(feed_id, ("A story", "https://loopback.example.com/a"), aged=False)

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_later_version_waits_for_the_settle_window(clean: None, feed_id, article):
    versions = await article(
        feed_id,
        ("First cut", "https://loopback.example.com/a"),
        ("Rewritten", "https://loopback.example.com/a"),
        aged=False,
    )
    await _capture(versions[0], status=200)

    assert await _due_urls() == []


async def test_a_settled_later_version_is_due(clean: None, feed_id, article):
    """The 404 Media case: the replacement gets captured too."""
    await _rules_read()
    versions = await article(
        feed_id,
        ("Full article", "https://loopback.example.com/a"),
        ("Truncated", "https://loopback.example.com/a"),
    )
    await _capture(versions[0], status=200)

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_superseded_version_is_never_due(clean: None, feed_id, article):
    """Only the head. Nobody reads superseded text, so nobody needs its page."""
    await _rules_read()
    await article(
        feed_id,
        ("First cut", "https://loopback.example.com/old"),
        ("Rewritten", "https://loopback.example.com/new"),
    )

    assert await _due_urls() == ["https://loopback.example.com/new"]


async def test_a_captured_version_is_not_due_again(clean: None, feed_id, article):
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(versions[0], status=200)

    assert await _due_urls() == []


async def test_a_failed_capture_waits_before_being_asked_again(clean: None, feed_id, article):
    """A 403 is worth recording and worth retrying, but not a minute later. Asking on
    every sweep is what made 25 doomed versions 88% of all article fetching."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(versions[0], status=403)

    assert await _due_urls() == []


async def test_a_failed_capture_is_due_once_its_backoff_elapses(clean: None, feed_id, article):
    """Backing off is not giving up — a publisher having a bad afternoon gets asked again."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(versions[0], status=403, ago=datetime.timedelta(hours=2))

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_version_that_keeps_refusing_is_given_up_on(clean: None, feed_id, article):
    """However long we wait. Medium 403s every article page it has, forever, and no
    amount of patience turns that into a page."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(
        versions[0],
        status=403,
        times=SETTINGS.capture_retry.max_failures,
        ago=datetime.timedelta(days=30),
    )

    assert await _due_urls() == []


async def test_an_item_over_the_version_cap_is_dropped(clean: None, feed_id, article):
    """The backstop. A live blog runs to forty-three rewrites and must not cost that."""
    rewrites = tuple(
        (f"Update {n}", "https://loopback.example.com/rolling")
        for n in range(SETTINGS.max_versions_per_item + 1)
    )
    await article(feed_id, *rewrites)

    assert await _due_urls() == []


async def test_a_blocked_item_is_never_due(clean: None, feed_id, article):
    """With the first version captured unconditionally, this is the only thing that stops
    a live blog costing anything at all."""
    await article(feed_id, ("Politics live", "https://loopback.example.com/politics/live/a"))
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/")

    assert await _due_urls() == []


async def test_an_unfetchable_link_is_skipped(clean: None, feed_id, article):
    """An aggregator can name something that was never a web resource."""
    await article(feed_id, ("Not a page", "newsletter:0:someone@example.com"))

    assert await _due_urls() == []


async def test_article_hosts_are_reported_for_the_robots_refresh(clean: None, feed_id, article):
    """The gap this closes: the feed host is not the article host."""
    await article(feed_id, ("A story", "https://news.example.org/politics/a"))

    assert await extract.article_hosts() == ["news.example.org"]


async def test_a_host_whose_robots_txt_was_never_read_is_left_alone(clean: None, feed_id, article):
    """Unknown rules read as permission everywhere else, which is right for a feed
    published for readers and wrong for crawling a publisher's pages. The refresh sweep
    writes a row for every host it visits, so this delays a new host rather than
    blocking it."""
    await article(feed_id, ("A story", "https://unasked.example.com/a"))

    assert await _due_urls() == []

    await _rules_read("unasked.example.com")
    assert await _due_urls() == ["https://unasked.example.com/a"]
