"""Feed failure state, derived. There is no column holding any of this."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Feed, FeedPoll, PollOutcome, Subscription
from old_news.politeness import resolve

MINUTE = datetime.timedelta(minutes=1)


@db.transactional
async def _feed(session: AsyncSession, url: str = "https://p.example.com/feed.xml") -> uuid.UUID:
    feed = Feed(url=url, host_id=await resolve(session, url))
    session.add(feed)
    await session.flush()
    session.add(Subscription(feed_id=feed.id))
    return feed.id


@db.transactional
async def _polls(session: AsyncSession, feed_id: uuid.UUID, *outcomes: tuple[str, int]) -> None:
    """Oldest first, a minute apart, so `polled_at` orders them predictably."""
    start = datetime.datetime.now(datetime.UTC) - len(outcomes) * MINUTE
    for n, (outcome, status) in enumerate(outcomes):
        session.add(
            FeedPoll(feed_id=feed_id, outcome=outcome, status=status, polled_at=start + n * MINUTE)
        )
    await session.flush()


@db.transactional
async def _state(session: AsyncSession, feed_id: uuid.UUID) -> tuple[int, bool]:
    row = (
        await session.execute(
            select(Feed.consecutive_failures, Feed.gone).where(Feed.id == feed_id)
        )
    ).one()
    return row.consecutive_failures, row.gone


FAILED = (PollOutcome.FAILED, 500)
OK = (PollOutcome.OK, 200)
NOT_MODIFIED = (PollOutcome.NOT_MODIFIED, 304)
DISALLOWED = (PollOutcome.DISALLOWED, 0)


async def test_a_feed_never_polled_has_no_failures(clean: None):
    assert await _state(await _feed()) == (0, False)


async def test_failures_are_counted_back_to_the_last_good_poll(clean: None):
    """Not the whole history — a feed that broke and recovered starts from zero."""
    feed_id = await _feed()
    await _polls(feed_id, FAILED, FAILED, OK, FAILED, FAILED, FAILED)

    assert await _state(feed_id) == (3, False)


async def test_a_304_ends_a_run_of_failures(clean: None):
    """The feed answered and had nothing new. That is a healthy poll, not a failure."""
    feed_id = await _feed()
    await _polls(feed_id, FAILED, FAILED, NOT_MODIFIED)

    assert await _state(feed_id) == (0, False)


async def test_a_robots_refusal_ends_a_run_too(clean: None):
    """Dropping the rule has to bring the feed back on its own, so it is not a failure."""
    feed_id = await _feed()
    await _polls(feed_id, FAILED, DISALLOWED)

    assert await _state(feed_id) == (0, False)


async def test_a_410_marks_the_feed_withdrawn_for_good(clean: None):
    """The one permanent answer, so the one that needs no threshold."""
    feed_id = await _feed()
    await _polls(feed_id, (PollOutcome.FAILED, 410))

    assert await _state(feed_id) == (1, True)


async def test_a_410_stays_withdrawn_even_after_a_later_success(clean: None):
    """A publisher does not un-say it by serving something later, and this is the only
    state that outlives a good poll."""
    feed_id = await _feed()
    await _polls(feed_id, (PollOutcome.FAILED, 410), OK)

    assert await _state(feed_id) == (0, True)


async def test_two_feeds_do_not_see_each_others_polls(clean: None):
    """The subquery correlates on feed_id, which is easy to get wrong and silent."""
    one = await _feed("https://one.example.com/feed.xml")
    two = await _feed("https://two.example.com/feed.xml")
    await _polls(one, FAILED, FAILED)

    assert await _state(one) == (2, False)
    assert await _state(two) == (0, False)
