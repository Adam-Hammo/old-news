import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from old_news import db
from old_news.db import Feed, Subscription
from old_news.subscriptions.service import add, export_opml, unsubscribe

FEED = "https://example.com/feed.xml"


async def test_a_feed_can_only_be_subscribed_once(clean: None):
    """One-to-one is the primary key, not a convention."""
    feed = await add(FEED)
    assert feed is not None

    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(Subscription(feed_id=feed.id, category="duplicate"))


async def test_subscribing_twice_is_a_no_op(clean: None):
    await add(FEED, category="News")

    assert await add(FEED, category="Different") is None

    async with db.session() as session:
        total = (await session.execute(select(func.count()).select_from(Feed))).scalar_one()
    assert total == 1


async def test_unsubscribing_keeps_the_feed_and_its_archive(clean: None):
    await add(FEED)

    assert await unsubscribe(FEED) is True

    async with db.session() as session:
        feeds = (await session.execute(select(func.count()).select_from(Feed))).scalar_one()
        subscription = (await session.execute(select(Subscription))).scalar_one()

    assert feeds == 1, "the archive outlives the subscription"
    assert subscription.active is False


async def test_resubscribing_reactivates_rather_than_duplicating(clean: None):
    await add(FEED, category="News")
    await unsubscribe(FEED)

    feed = await add(FEED, category="News")

    assert feed is not None
    async with db.session() as session:
        subscription = (await session.execute(select(Subscription))).scalar_one()
    assert subscription.active is True


async def test_unsubscribing_twice_reports_no_change(clean: None):
    await add(FEED)
    await unsubscribe(FEED)

    assert await unsubscribe(FEED) is False


async def test_export_lists_only_active_subscriptions(clean: None):
    await add(FEED, title="Kept", category="News")
    await add("https://example.com/other.xml", title="Dropped", category="News")
    await unsubscribe("https://example.com/other.xml")

    exported = await export_opml()

    assert b"Kept" in exported
    assert b"Dropped" not in exported
