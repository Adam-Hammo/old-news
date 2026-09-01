"""The relationships that save every reader rewriting an anti-join."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import Extraction, FeedExtraction, Item, ItemVersion, PageExtraction
from old_news.extract.service import extract_feed, extract_page

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


async def test_a_version_nothing_has_read_has_no_reading_body(clean: None, feed_id, article):
    """A version scoped question, unlike the item's: nothing has read this one yet."""
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


async def test_the_reading_body_prefers_a_fuller_feed(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """A full-text feed beats its own page, so the page reading does not always win. Both
    are readings of one version now, which is the comparison this replaced."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    await stored_page(version_id, page("guardian-article.html").encode())
    extracted = await extract_page(version_id, SETTINGS)
    assert extracted is not None
    await stored_feed_text(version_id, f"<p>{'the whole article, in the feed. ' * 100}</p>" * 6)
    from_feed = await extract_feed(version_id, SETTINGS)
    assert from_feed is not None

    assert len(from_feed.body) > len(extracted.body)
    assert await _version_reading_body(version_id) == from_feed.body
    assert await _item_reading_body(await _item_id(version_id)) == from_feed.body


async def test_another_article_s_readings_do_not_answer_this_one(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """Both halves of `reading_body` are correlated subqueries, and both silently answer
    for the whole archive if the correlation is left to SQLAlchemy to infer."""
    mine = (await article(feed_id, ("Mine", "https://loopback.example.com/mine")))[0]
    theirs = (await article(feed_id, ("Theirs", "https://loopback.example.com/theirs")))[0]

    await stored_feed_text(mine, f"<p>{'my own feed text. ' * 60}</p>" * 4)
    assert await extract_feed(mine, SETTINGS) is not None
    await stored_page(theirs, page("guardian-article.html").encode())
    assert await extract_page(theirs, SETTINGS) is not None

    body = await _version_reading_body(mine)

    assert "my own feed text" in body
    assert await _item_reading_body(await _item_id(mine)) == body


async def test_a_superseded_extractor_does_not_win_on_length(
    clean: None, feed_id, article, stored_feed_text
):
    """Per source, and the newest of each: an older extractor that happened to keep more
    of the page is a stale reading, not a fuller one."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    capture_id = await stored_feed_text(version_id, "<p>x</p>")

    async with db.session() as session:
        for extractor_version, body in (("0", "the older, longer reading" * 40), ("1", "current")):
            session.add(
                FeedExtraction(
                    item_version_id=version_id,
                    feed_capture_id=capture_id,
                    extractor="test",
                    extractor_version=extractor_version,
                    body=body,
                    created_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(seconds=int(extractor_version)),
                )
            )
            await session.flush()

    assert await _version_reading_body(version_id) == "current"


@db.transactional
async def _loaded(session: AsyncSession, version_id: uuid.UUID) -> ItemVersion:
    return (
        await session.execute(
            select(ItemVersion)
            .where(ItemVersion.id == version_id)
            .options(
                joinedload(ItemVersion.feed_capture),
                joinedload(ItemVersion.feed_extraction),
                joinedload(ItemVersion.page_extraction),
            )
        )
    ).scalar_one()


async def test_the_python_half_agrees_with_the_sql_half(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """`lazy="raise"` means the only way to find out that a bridge is wrong is to load it,
    and the Python getter is the caller that keeps the two definitions honest."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    await stored_feed_text(version_id, f"<p>{'a teaser. ' * 30}</p>" * 4)
    assert await extract_feed(version_id, SETTINGS) is not None
    await stored_page(version_id, page("guardian-article.html").encode())
    assert await extract_page(version_id, SETTINGS) is not None

    version = await _loaded(version_id)

    assert version.feed_extraction is not None
    assert version.page_extraction is not None
    assert version.reading_body == await _version_reading_body(version_id)
    assert version.has_feed_text


async def test_the_feed_wins_a_tie_by_name_not_by_spelling(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """`READING_PREFERENCE`, not `ORDER BY source`. Two readings of equal length used to be
    ranked by how their discriminators happened to sort."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    capture_id = await stored_feed_text(version_id, "<p>x</p>")
    page_capture_id = await stored_page(version_id, b"<html></html>")

    async with db.session() as session:
        session.add(
            FeedExtraction(
                item_version_id=version_id,
                feed_capture_id=capture_id,
                extractor="test",
                extractor_version="0",
                body="feed reading, tied.",
            )
        )
        session.add(
            PageExtraction(
                item_version_id=version_id,
                page_capture_id=page_capture_id,
                extractor="test",
                extractor_version="0",
                body="page reading, tied.",
            )
        )
        await session.flush()

    assert await _version_reading_body(version_id) == "feed reading, tied."


async def test_a_page_of_boilerplate_does_not_beat_a_feed_that_carries_the_picture(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """The comic case. Neither reading is prose, so length stops being evidence: 300
    characters of template is not more article than the picture that was published."""
    version_id = (await article(feed_id, ("Geology Class", "https://loopback.example.com/a")))[0]
    await stored_page(version_id, page("xkcd-page.html").encode())
    boilerplate = await extract_page(version_id, SETTINGS)
    assert boilerplate is not None
    await stored_feed_text(version_id, page("xkcd-feed-item.html"))
    comic = await extract_feed(version_id, SETTINGS)
    assert comic is not None

    assert len(comic.body) < len(boilerplate.body)
    assert await _version_reading_body(version_id) == comic.body


async def test_a_feed_that_dropped_the_headings_does_not_beat_the_page_that_kept_them(
    clean: None, feed_id, article, page, stored_page, stored_feed_text
):
    """Both carry the article and the feed is the longer by a hair, which used to settle
    it. What the reader wants is the one still divided into sections."""
    version_id = (await article(feed_id, ("An article", "https://loopback.example.com/a")))[0]
    await stored_page(version_id, page("conversation-article.html").encode())
    from_page = await extract_page(version_id, SETTINGS)
    assert from_page is not None
    await stored_feed_text(version_id, page("conversation-feed-item.html"))
    from_feed = await extract_feed(version_id, SETTINGS)
    assert from_feed is not None

    assert from_feed.char_count > from_page.char_count
    assert from_page.structure_count > from_feed.structure_count
    assert await _version_reading_body(version_id) == from_page.body
