"""A host's failure count, derived. There is no column holding any of this."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import CAPTURE_POLICY, CaptureOutcome, Host, PageCapture
from old_news.politeness import ensure

HOST = "loopback.example.com"
MINUTE = datetime.timedelta(minutes=1)


@db.transactional
async def _visits(
    session: AsyncSession, version_id: uuid.UUID, *outcomes: str, policy: str = CAPTURE_POLICY
) -> None:
    """Oldest first, a minute apart, so `fetched_at` orders them predictably."""
    host_id = await ensure(session, HOST)
    start = datetime.datetime.now(datetime.UTC) - len(outcomes) * MINUTE
    for n, outcome in enumerate(outcomes):
        session.add(
            PageCapture(
                item_version_id=version_id,
                host_id=host_id,
                url=f"https://{HOST}/{n}",
                status=0,
                outcome=outcome,
                body_hash=b"0" * 32,
                fetched_at=start + n * MINUTE,
                capture_policy=policy,
            )
        )
    await session.flush()


@db.transactional
async def _failures(session: AsyncSession) -> int:
    return (
        await session.execute(select(Host.capture_failures).where(Host.name == HOST))
    ).scalar_one()


@db.transactional
async def _host(session: AsyncSession) -> None:
    await ensure(session, HOST)


async def test_a_host_never_visited_has_no_failures(clean: None):
    await _host()

    assert await _failures() == 0


async def test_failures_are_counted_back_to_the_last_success(clean: None, feed_id, article):
    """Not the whole history. A publisher that broke and recovered starts again."""
    version_id = (await article(feed_id, ("A story", f"https://{HOST}/a")))[0]
    await _visits(
        version_id,
        CaptureOutcome.FAILED,
        CaptureOutcome.OK,
        CaptureOutcome.FAILED,
        CaptureOutcome.FAILED,
    )

    assert await _failures() == 2


async def test_a_dead_link_is_stepped_over_rather_than_counted(clean: None, feed_id, article):
    """`gone` neither counts against a host nor clears a run of real refusals."""
    version_id = (await article(feed_id, ("A story", f"https://{HOST}/a")))[0]
    await _visits(version_id, CaptureOutcome.FAILED, CaptureOutcome.GONE, CaptureOutcome.FAILED)

    assert await _failures() == 2


async def test_the_visits_we_declined_to_send_do_not_count(clean: None, feed_id, article):
    """The whole reason they can be recorded at all. A refusal we chose says nothing
    about the publisher, so writing it down must not move the breaker that chose it."""
    version_id = (await article(feed_id, ("A story", f"https://{HOST}/a")))[0]
    await _visits(
        version_id,
        CaptureOutcome.REFUSED,
        CaptureOutcome.DISALLOWED,
        CaptureOutcome.UNKNOWN_RULES,
    )

    assert await _failures() == 0


async def test_failures_under_an_older_policy_are_forgiven(clean: None, feed_id, article):
    """A host that refused the old way of asking has not refused the new one."""
    version_id = (await article(feed_id, ("A story", f"https://{HOST}/a")))[0]
    await _visits(version_id, CaptureOutcome.FAILED, CaptureOutcome.FAILED, policy="0")

    assert await _failures() == 0
