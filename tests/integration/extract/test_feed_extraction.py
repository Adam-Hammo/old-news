"""Reading the text a feed already gave us, as a row of the same shape as a page's."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import Extraction, ExtractionSource, ItemVersion
from old_news.extract.service import extract_feed

SETTINGS = ExtractSettings()

ARTICLE = ("<p>" + "A paragraph with enough words in it to look like prose. " * 12 + "</p>") * 4
TEASER = "<p>Read the rest on our site.</p>"


@db.transactional
async def _set_content(session: AsyncSession, version_id: uuid.UUID, content: str) -> None:
    version = await session.get(ItemVersion, version_id)
    assert version is not None
    version.content = content


@db.transactional
async def _extractions(session: AsyncSession, version_id: uuid.UUID) -> list[Extraction]:
    rows = await session.execute(
        select(Extraction)
        .where(Extraction.item_version_id == version_id)
        .order_by(Extraction.source)
    )
    return list(rows.scalars().all())


async def test_feed_text_becomes_an_extraction_with_no_capture(clean: None, feed_id, article):
    """The same object a page produces, minus the artefact it does not have."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert stored.source == ExtractionSource.FEED
    assert stored.page_capture_id is None
    assert stored.ok
    assert stored.char_count > SETTINGS.min_body_chars


async def test_a_teaser_is_stored_and_marked_short(clean: None, feed_id, article):
    """Most of this corpus is teasers. Knowing which is the whole point, so the row is
    kept and judged rather than thrown away."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, TEASER)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert not stored.ok
    assert stored.note


async def test_a_feed_that_carried_nothing_produces_no_row(clean: None, feed_id, article):
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, "")

    assert await extract_feed(version_id, SETTINGS) is None


async def test_no_metadata_is_claimed_from_a_fragment(clean: None, feed_id, article):
    """`extract_metadata` on a fragment returns the first heading in the body — "Support
    Bellingcat", "Today's links". The feed states its own title and author, and those are
    already on the version."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, "<h2>Support Bellingcat</h2>" + ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert stored.title == ""
    assert stored.byline == ""
    assert stored.site_name == ""


@db.transactional
async def _page_extraction(session: AsyncSession, version_id: uuid.UUID, capture_id: uuid.UUID):
    session.add(
        Extraction(
            item_version_id=version_id,
            source=ExtractionSource.PAGE,
            page_capture_id=capture_id,
            extractor="test",
            extractor_version="0",
            body="From the page.",
        )
    )


async def test_both_sources_coexist_for_one_version(clean: None, feed_id, article, stored_page):
    """The point of the whole change: two readings of one article, side by side, because
    they are the same kind of row. The unique constraint has to allow exactly this."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)
    await _page_extraction(version_id, await stored_page(version_id, b"<html></html>"))

    await extract_feed(version_id, SETTINGS)

    stored = await _extractions(version_id)
    assert [row.source for row in stored] == [ExtractionSource.FEED, ExtractionSource.PAGE]
    assert stored[0].page_capture_id is None and stored[1].page_capture_id is not None


async def test_re_reading_the_same_feed_text_rewrites_its_own_row(clean: None, feed_id, article):
    """Idempotent per source, the same way the page path is."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    first = await extract_feed(version_id, SETTINGS)
    second = await extract_feed(version_id, SETTINGS)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(await _extractions(version_id)) == 1


async def test_a_feed_extraction_may_not_name_a_capture(clean: None, feed_id, article):
    """And a page one must. The constraint is what stops either shape being stored wrong."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]

    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(
                Extraction(
                    item_version_id=version_id,
                    source=ExtractionSource.PAGE,
                    page_capture_id=None,
                    extractor="test",
                    extractor_version="0",
                )
            )


async def test_the_sweep_finds_versions_with_feed_text_and_no_reading(
    clean: None, feed_id, article
):
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    assert await extract.due_feed_extractions(50) == [version_id]

    await extract_feed(version_id, SETTINGS)

    assert await extract.due_feed_extractions(50) == []
