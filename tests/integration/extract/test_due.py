"""What is worth fetching. Every condition in `due_captures`, one at a time."""

import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import (
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
async def _rule(session: AsyncSession, **values) -> None:
    session.add(TrainingRule(source=RuleSource.HAND, blocks=True, **values))
    await session.flush()


@db.transactional
async def _rules_read(session: AsyncSession, host: str = "loopback.example.com") -> None:
    """A host whose robots.txt has been asked for. Most of these tests need it."""
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
    """Not settled, and due anyway, so every article has something."""
    await _rules_read()
    await article(feed_id, ("A story", "https://loopback.example.com/a"), aged=False)

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_later_version_waits_for_the_settle_window(clean: None, feed_id, article, captures):
    await _rules_read()
    versions = await article(
        feed_id,
        ("First cut", "https://loopback.example.com/a"),
        ("Rewritten", "https://loopback.example.com/a"),
        aged=False,
    )
    await captures(versions[0], status=200)

    assert await _due_urls() == []


async def test_a_settled_later_version_is_due(clean: None, feed_id, article, captures):
    """The 404 Media case: the replacement gets captured too."""
    await _rules_read()
    versions = await article(
        feed_id,
        ("Full article", "https://loopback.example.com/a"),
        ("Truncated", "https://loopback.example.com/a"),
    )
    await captures(versions[0], status=200)

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


async def test_a_captured_version_is_not_due_again(clean: None, feed_id, article, captures):
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(versions[0], status=200)

    assert await _due_urls() == []


async def test_a_failed_capture_waits_before_being_asked_again(
    clean: None, feed_id, article, captures
):
    """Worth retrying, but not a minute later."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(versions[0], status=403)

    assert await _due_urls() == []


async def test_a_failed_capture_is_due_once_its_backoff_elapses(
    clean: None, feed_id, article, captures
):
    """Backing off is not giving up — a publisher having a bad afternoon gets asked again."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(versions[0], status=403, ago=datetime.timedelta(hours=2))

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_version_that_keeps_refusing_is_given_up_on(
    clean: None, feed_id, article, captures
):
    """However long we wait."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(
        versions[0],
        status=403,
        times=SETTINGS.capture_retry.max_failures,
        ago=datetime.timedelta(days=30),
    )

    assert await _due_urls() == []


async def test_an_item_over_the_version_cap_is_dropped(clean: None, feed_id, article):
    """The backstop. A live blog runs to forty-three rewrites and must not cost that."""
    await _rules_read()
    rewrites = tuple(
        (f"Update {n}", "https://loopback.example.com/rolling")
        for n in range(SETTINGS.max_versions_per_item + 1)
    )
    await article(feed_id, *rewrites)

    assert await _due_urls() == []


async def test_a_blocked_item_is_never_due(clean: None, feed_id, article):
    """With the first version captured unconditionally, this is what caps a live blog."""
    await _rules_read()
    await article(feed_id, ("Politics live", "https://loopback.example.com/politics/live/a"))
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/")

    assert await _due_urls() == []


async def test_an_unfetchable_link_is_skipped(clean: None, feed_id, article):
    """An aggregator can name something that was never a web resource."""
    await article(feed_id, ("Not a page", "newsletter:0:someone@example.com"))

    assert await _due_urls() == []


async def test_article_hosts_are_reported_for_the_robots_refresh(
    clean: None, feed_id, article, bystander_host
):
    """The gap this closes: the feed host is not the article host.

    Compared as a set rather than with `in`, which is both a weaker claim — it would hold
    for `news.example.org.attacker.test` — and the shape CodeQL reads as URL sanitisation.
    """
    await article(feed_id, ("A story", "https://news.example.org/politics/a"))

    hosts = set(await extract.article_hosts()) - {bystander_host}

    assert hosts == {"news.example.org"}


async def test_a_host_whose_robots_txt_was_never_read_is_left_alone(clean: None, feed_id, article):
    """Silence reads as permission elsewhere, which is wrong for crawling."""
    await article(feed_id, ("A story", "https://unasked.example.com/a"))

    assert await _due_urls() == []

    await _rules_read("unasked.example.com")
    assert await _due_urls() == ["https://unasked.example.com/a"]


async def test_refusals_under_an_older_policy_do_not_count(clean: None, feed_id, article, captures):
    """Failures against a name that could never answer must not spend the limit."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(
        versions[0],
        status=0,
        times=SETTINGS.capture_retry.max_failures * 2,
        ago=datetime.timedelta(hours=2),
        policy="0",
    )

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_refusals_under_the_current_policy_still_count(
    clean: None, feed_id, article, captures
):
    """Otherwise the forgiveness is unbounded and the retry loop comes straight back."""
    await _rules_read()
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(
        versions[0],
        status=403,
        times=SETTINGS.capture_retry.max_failures,
        ago=datetime.timedelta(hours=1),
    )

    assert await _due_urls() == []


async def test_a_version_refused_on_a_shut_host_is_not_selected_again(
    clean: None, feed_id, article, captures
):
    """The outage: a decline wrote nothing, so the version stayed due forever."""
    await _rules_read()
    doomed = (await article(feed_id, ("Blocked", "https://loopback.example.com/b")))[0]
    await captures(
        doomed, status=0, outcome=CaptureOutcome.REFUSED, url="https://loopback.example.com/b"
    )
    # Enough real failures elsewhere on the host that it counts as refusing everyone.
    other = (await article(feed_id, ("Also blocked", "https://loopback.example.com/c")))[0]
    await captures(other, status=403, times=SETTINGS.host_failure_threshold)

    assert await _due_urls() == []


async def test_a_shut_host_does_not_crowd_out_a_healthy_one(
    clean: None, feed_id, article, captures
):
    """The shape of the outage."""
    await _rules_read()
    await _rules_read("healthy.example.com")

    # Separate items, so each is a head of its own and all of them compete for the batch.
    for n in range(9):
        version_id = (
            await article(feed_id, (f"Blocked {n}", f"https://loopback.example.com/b{n}"))
        )[0]
        await captures(
            version_id,
            status=0,
            outcome=CaptureOutcome.REFUSED,
            url=f"https://loopback.example.com/b{n}",
        )
    shut = (await article(feed_id, ("Refusing", "https://loopback.example.com/x")))[0]
    await captures(shut, status=403, times=SETTINGS.host_failure_threshold)

    await article(feed_id, ("Fine", "https://healthy.example.com/fine"))

    # A batch of two. Ten versions on the shut host are older and would have taken both.
    assert await _due_urls(limit=2) == ["https://healthy.example.com/fine"]


async def test_a_refusal_we_declined_to_send_does_not_spend_a_try(
    clean: None, feed_id, article, captures
):
    """Only visits actually sent count against a page's tries."""
    await _rules_read()
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await captures(
        version_id,
        status=0,
        outcome=CaptureOutcome.REFUSED,
        times=SETTINGS.capture_retry.max_failures * 2,
    )

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_a_page_robots_forbade_is_not_asked_for_again(
    clean: None, feed_id, article, captures
):
    """The same starvation, different trigger."""
    await _rules_read()
    version_id = (await article(feed_id, ("Forbidden", "https://loopback.example.com/a")))[0]
    await captures(version_id, status=0, outcome=CaptureOutcome.DISALLOWED)

    assert await _due_urls() == []


async def test_re_reading_the_rules_makes_a_forbidden_page_a_candidate_again(
    clean: None, feed_id, article, captures
):
    """robots.txt is a cache, not a verdict. Dropping the rule brings the page back."""
    await _rules_read()
    version_id = (await article(feed_id, ("Forbidden", "https://loopback.example.com/a")))[0]
    await captures(version_id, status=0, outcome=CaptureOutcome.DISALLOWED, ago=MINUTE)
    await _refresh_rules()

    assert await _due_urls() == ["https://loopback.example.com/a"]


async def test_succeeded_reads_the_outcome_in_sql_too(clean: None, feed_id, article, captures):
    """Nothing writes a 2xx row with a declined outcome today, which is why this row is
    built by hand: `succeeded` and `ix_page_captures_succeeded` are the same predicate, and
    a partial index only serves a query whose predicate implies the index's. The two have
    to move together, so what they mean is worth stating rather than inferring."""
    versions = await article(feed_id, ("A story", "https://loopback.example.com/a"))
    await captures(versions[0], status=200, outcome=CaptureOutcome.DISALLOWED)

    async with db.session() as session:
        answered = (
            await session.execute(
                select(PageCapture.succeeded).where(PageCapture.item_version_id == versions[0])
            )
        ).scalar_one()

    assert not answered
