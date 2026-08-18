"""The `@db.transactional` contract, against a real Postgres."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Feed
from old_news.politeness import resolve


@db.transactional
async def _count_feeds(session: AsyncSession) -> int:
    return (await session.execute(text("SELECT count(*) FROM feeds"))).scalar_one()


@db.transactional
async def _add_feed(session: AsyncSession, url: str) -> None:
    session.add(Feed(url=url, host_id=await resolve(session, url)))


@db.transactional
async def _add_then_fail(session: AsyncSession, url: str) -> None:
    session.add(Feed(url=url, host_id=await resolve(session, url)))
    await session.flush()
    raise RuntimeError("boom")


@db.transactional
async def _opens_a_second_transaction(session: AsyncSession) -> int:
    return await _count_feeds()


async def test_a_decorated_function_commits(clean: None):
    await _add_feed("https://committed.example/feed.xml")

    assert await _count_feeds() == 1


async def test_a_decorated_function_rolls_back_on_error(clean: None):
    """One function is one unit of work, so a failure leaves nothing behind."""
    with pytest.raises(RuntimeError):
        await _add_then_fail("https://doomed.example/feed.xml")

    assert await _count_feeds() == 0


async def test_nesting_is_refused(clean: None):
    """A transaction inside another would commit halfway through the outer one, and
    the inner call is usually several frames away — so it fails loudly."""
    with pytest.raises(RuntimeError, match="already open"):
        await _opens_a_second_transaction()


async def test_the_guard_is_released_afterwards(clean: None):
    """Otherwise one refusal would poison every later transaction on the task."""
    with pytest.raises(RuntimeError, match="already open"):
        await _opens_a_second_transaction()

    assert await _count_feeds() == 0
