"""Which items a blocking rule takes out, and which it must leave alone."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, training
from old_news.db import Dimension, Document, Item, ItemVersion, RuleSource, TrainingRule
from old_news.subscriptions.service import add


async def _feed(url: str) -> uuid.UUID:
    feed = await add(url)
    assert feed is not None
    return feed.id


@db.transactional
async def _item(session: AsyncSession, feed_id: uuid.UUID, *, title: str, url: str) -> uuid.UUID:
    """A version has to come from a document, so one is made to hang it off."""
    document = Document(feed_id=feed_id, status=200, body_hash=b"0" * 32, body=b"<rss/>")
    item = Item(feed_id=feed_id, guid=url, identity_key=url, identity_source="link")
    session.add_all([document, item])
    await session.flush()
    session.add(
        ItemVersion(
            item_id=item.id,
            document_id=document.id,
            title=title,
            url=url,
            content_hash=b"0" * 32,
        )
    )
    await session.flush()
    return item.id


@db.transactional
async def _rule(session: AsyncSession, **values) -> None:
    session.add(TrainingRule(source=RuleSource.HAND, **values))
    await session.flush()


@db.transactional
async def _blocked_titles(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        select(ItemVersion.title)
        .join(Item, Item.id == ItemVersion.item_id)
        .where(training.blocked(ItemVersion, Item))
    )
    return sorted(rows.scalars().all())


async def test_a_url_pattern_blocks_only_matching_items(clean: None):
    feed_id = await _feed("https://loopback.example.com/feed.xml")
    await _item(
        feed_id, title="Politics live", url="https://loopback.example.com/politics/live/2026/aug"
    )
    await _item(feed_id, title="A finished article", url="https://loopback.example.com/news/one")
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/", blocks=True)

    assert await _blocked_titles() == ["Politics live"]


async def test_a_title_phrase_blocks_the_other_convention(clean: None):
    feed_id = await _feed("https://loopback.example.com/feed.xml")
    await _item(feed_id, title="Live: the second test", url="https://loopback.example.com/sport/a")
    await _item(feed_id, title="Alive and well", url="https://loopback.example.com/sport/b")
    await _rule(dimension=Dimension.TITLE_PHRASE, pattern="live:", blocks=True)

    assert await _blocked_titles() == ["Live: the second test"]


async def test_a_rule_that_does_not_block_blocks_nothing(clean: None):
    """`blocks` is the tier, not the existence of the row. Thumbs will not filter."""
    feed_id = await _feed("https://loopback.example.com/feed.xml")
    await _item(feed_id, title="Politics live", url="https://loopback.example.com/live/a")
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/", blocks=False)

    assert await _blocked_titles() == []


async def test_a_per_feed_rule_leaves_other_feeds_alone(clean: None):
    """The override half of "global, with per-feed overrides"."""
    one = await _feed("https://one.example.com/feed.xml")
    two = await _feed("https://two.example.com/feed.xml")
    await _item(one, title="Blocked here", url="https://one.example.com/live/a")
    await _item(two, title="Fine over here", url="https://two.example.com/live/a")
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/", blocks=True, feed_id=one)

    assert await _blocked_titles() == ["Blocked here"]


async def test_an_underscore_in_a_pattern_is_not_a_wildcard(clean: None):
    """Postgres LIKE would treat it as any character, and URLs are full of them."""
    feed_id = await _feed("https://loopback.example.com/feed.xml")
    await _item(feed_id, title="Real", url="https://loopback.example.com/live_blog/a")
    await _item(feed_id, title="Coincidence", url="https://loopback.example.com/liveXblog/a")
    await _rule(dimension=Dimension.URL_PATTERN, pattern="live_blog", blocks=True)

    assert await _blocked_titles() == ["Real"]


async def test_a_dimension_with_no_matching_code_cannot_be_stored(clean: None):
    """A rule that could never fire is worse than a missing feature. The enum stops it in
    Python; this is the database refusing it too, for anything the ORM did not write."""
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO training_rules (dimension, pattern, blocks, source) "
                    "VALUES ('author', 'someone', true, 'hand')"
                )
            )


async def test_the_same_global_rule_cannot_be_added_twice(clean: None):
    await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/", blocks=True)

    with pytest.raises(IntegrityError):
        await _rule(dimension=Dimension.URL_PATTERN, pattern="/live/", blocks=True)
