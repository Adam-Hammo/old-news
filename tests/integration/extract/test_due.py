"""What is worth fetching. Every condition in `due_captures`, one at a time."""

import datetime
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import (
    CAPTURE_POLICY,
    CaptureOutcome,
    Dimension,
    PageCapture,
    RobotsPolicy,
    RuleSource,
    TrainingRule,
)
from old_news.politeness import ensure

SETTINGS = ExtractSettings()
MINUTE = datetime.timedelta(minutes=1)


@db.transactional
async def _capture(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    status: int,
    ago: datetime.timedelta = datetime.timedelta(0),
    times: int = 1,
    policy: str = CAPTURE_POLICY,
    outcome: str | None = None,
    host: str = "loopback.example.com",
    url: str = "https://loopback.example.com/a",
) -> None:
    host_id = await ensure(session, host)
    if outcome is None:
        outcome = CaptureOutcome.OK if 200 <= status < 300 else CaptureOutcome.FAILED
    for _ in range(times):
        session.add(
            PageCapture(
                item_version_id=version_id,
                host_id=host_id,
                url=url,
                status=status,
                outcome=outcome,
                body_hash=b"0" * 32,
                fetched_at=datetime.datetime.now(datetime.UTC) - ago,
                capture_policy=policy,
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


@db.transactional
async def _refresh_rules(session: AsyncSession, host: str = "loopback.example.com") -> None:
    """The robots sweep coming back around, which is what re-opens a forbidden page."""
    await session.execute(
        update(RobotsPolicy)
        .where(RobotsPolicy.host_id == await ensure(session, host))
        .values(fetched_at=datetime.datetime.now(datetime.UTC))
    )


async def _due_urls(limit: int = 50) -> list[str]:
    return sorted(item.url for item in await extract.due_captures(SETTINGS, limit=limit))


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


async def test_refusals_under_an_older_policy_do_not_count(clean: None, feed_id, article):
    """theclimatebrink links its articles at an apex with no DNS record, so 15 versions
    burned through the limit while we were asking a name that could never answer. The
    `www.` retry could not reach them, because it only runs on a version still selected."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(
        versions[0],
        status=0,
        times=SETTINGS.capture_retry.max_failures * 2,
        ago=datetime.timedelta(hours=2),
        policy="0",
    )

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_refusals_under_the_current_policy_still_count(clean: None, feed_id, article):
    """Otherwise the forgiveness is unbounded and the retry loop comes straight back."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await _capture(
        versions[0],
        status=403,
        times=SETTINGS.capture_retry.max_failures,
        ago=datetime.timedelta(hours=1),
    )

    assert await _due_urls() == []


async def test_a_version_refused_on_a_shut_host_is_not_selected_again(
    clean: None, feed_id, article
):
    """The outage. Declining at fetch time used to write nothing, so the version stayed
    due, led the batch by age, and took the same slot every minute — twenty-five of them
    captured nothing for three hours. The decline is a row now, and the row is what says
    we have been here."""
    await _rules_read()
    doomed = (await article(feed_id, ("Blocked", "https://loopback.example.com/b")))[0]
    await _capture(
        doomed, status=0, outcome=CaptureOutcome.REFUSED, url="https://loopback.example.com/b"
    )
    # Enough real failures elsewhere on the host that it counts as refusing everyone.
    other = (await article(feed_id, ("Also blocked", "https://loopback.example.com/c")))[0]
    await _capture(other, status=403, times=SETTINGS.host_failure_threshold)

    assert await _due_urls() == []


async def test_a_shut_host_does_not_crowd_out_a_healthy_one(clean: None, feed_id, article):
    """The shape of the outage. Older versions on a refusing host must not fill the batch
    ahead of the one that would succeed."""
    await _rules_read()
    await _rules_read("healthy.example.com")

    # Separate items, so each is a head of its own and all of them compete for the batch.
    for n in range(9):
        version_id = (
            await article(feed_id, (f"Blocked {n}", f"https://loopback.example.com/b{n}"))
        )[0]
        await _capture(
            version_id,
            status=0,
            outcome=CaptureOutcome.REFUSED,
            url=f"https://loopback.example.com/b{n}",
        )
    shut = (await article(feed_id, ("Refusing", "https://loopback.example.com/x")))[0]
    await _capture(shut, status=403, times=SETTINGS.host_failure_threshold)

    await article(feed_id, ("Fine", "https://healthy.example.com/fine"))

    # A batch of two. Ten versions on the shut host are older and would have taken both.
    assert await _due_urls(limit=2) == ["https://healthy.example.com/fine"]


async def test_a_refusal_we_declined_to_send_does_not_spend_a_try(clean: None, feed_id, article):
    """A host shut for an afternoon must not write off every article on it. Only the
    visits actually sent count against a page's limited tries."""
    await _rules_read()
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _capture(
        version_id,
        status=0,
        outcome=CaptureOutcome.REFUSED,
        times=SETTINGS.capture_retry.max_failures * 2,
    )

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_page_robots_forbade_is_not_asked_for_again(clean: None, feed_id, article):
    """The same starvation, different trigger. Selection checks only whether a host's
    rules have been read, so a host that has them and forbids the path would be chosen
    every sweep and declined every time."""
    await _rules_read()
    version_id = (await article(feed_id, ("Forbidden", "https://loopback.example.com/a")))[0]
    await _capture(version_id, status=0, outcome=CaptureOutcome.DISALLOWED)

    assert await _due_urls() == []


async def test_re_reading_the_rules_makes_a_forbidden_page_a_candidate_again(
    clean: None, feed_id, article
):
    """robots.txt is a cache, not a verdict. Dropping the rule brings the page back."""
    await _rules_read()
    version_id = (await article(feed_id, ("Forbidden", "https://loopback.example.com/a")))[0]
    await _capture(version_id, status=0, outcome=CaptureOutcome.DISALLOWED, ago=MINUTE)
    await _refresh_rules()

    assert await _due_urls() == ["https://loopback.example.com/a"]
