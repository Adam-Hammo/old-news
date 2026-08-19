"""The relationships that save every reader rewriting an anti-join."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import Extraction, Item, ItemVersion
from old_news.extract.service import extract_page

SETTINGS = ExtractSettings()


@db.transactional
async def _item_extraction(session: AsyncSession, item_id: uuid.UUID) -> Extraction | None:
    item = (
        await session.execute(
            select(Item).where(Item.id == item_id).options(joinedload(Item.current_extraction))
        )
    ).scalar_one()
    return item.current_extraction


@db.transactional
async def _version_reading_body(session: AsyncSession, version_id: uuid.UUID) -> str:
    return (
        await session.execute(select(ItemVersion.reading_body).where(ItemVersion.id == version_id))
    ).scalar_one()


@db.transactional
async def _item_id(session: AsyncSession, version_id: uuid.UUID) -> uuid.UUID:
    return (
        await session.execute(select(ItemVersion.item_id).where(ItemVersion.id == version_id))
    ).scalar_one()


@db.transactional
async def _item_reading_body(session: AsyncSession, item_id: uuid.UUID) -> str:
    return (await session.execute(select(Item.reading_body).where(Item.id == item_id))).scalar_one()


async def test_an_item_with_nothing_extracted_has_no_current_extraction(
    clean: None, feed_id, article
):
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]

    assert await _item_extraction(await _item_id(version_id)) is None


async def test_an_edit_does_not_blank_the_article_while_its_page_waits(
    clean: None, feed_id, article, page, stored_page
):
    """The hole this relationship exists to avoid: a new head version has no capture for an
    hour, and the previous version's extraction is right there."""
    first, second = await article(
        feed_id,
        ("First cut", "https://loopback.example.com/a"),
        ("Rewritten", "https://loopback.example.com/a"),
    )
    await stored_page(first, page("guardian-article.html").encode())
    extracted = await extract_page(first, SETTINGS)
    assert extracted is not None

    item_id = await _item_id(second)
    current = await _item_extraction(item_id)

    assert current is not None
    assert current.id == extracted.id


async def test_the_reading_body_falls_back_to_the_feed_without_an_extraction(
    clean: None, feed_id, article
):
    """A version scoped question, unlike the item's: this version has no text of its own."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]

    assert await _version_reading_body(version_id) == ""


async def test_the_reading_body_prefers_the_extraction_over_a_teaser(
    clean: None, feed_id, article, page, stored_page
):
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    await stored_page(version_id, page("guardian-article.html").encode())
    extracted = await extract_page(version_id, SETTINGS)
    assert extracted is not None

    assert await _version_reading_body(version_id) == extracted.body


async def test_the_item_reading_body_survives_an_edit(
    clean: None, feed_id, article, page, stored_page
):
    """The same hole as `current_extraction`, one level up: a reader must not be handed a
    teaser because the publisher touched the article an hour ago."""
    first, second = await article(
        feed_id,
        ("First cut", "https://loopback.example.com/a"),
        ("Rewritten", "https://loopback.example.com/a"),
    )
    await stored_page(first, page("guardian-article.html").encode())
    extracted = await extract_page(first, SETTINGS)
    assert extracted is not None

    item_id = await _item_id(second)

    # The head version knows nothing; the item still has the article.
    assert await _version_reading_body(second) == ""
    assert await _item_reading_body(item_id) == extracted.body


async def test_the_item_reading_body_prefers_a_fuller_feed(clean: None, feed_id, article):
    """A full-text feed beats its own page, so the extraction does not always win."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]

    async with db.session() as session:
        version = (
            await session.execute(select(ItemVersion).where(ItemVersion.id == version_id))
        ).scalar_one()
        version.content = "the whole article, published straight to the feed"

    assert await _item_reading_body(await _item_id(version_id)) == (
        "the whole article, published straight to the feed"
    )
