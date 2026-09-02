"""Reading the text a feed already gave us, as a child row beside a page's."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import (
    Extraction,
    ExtractionSource,
    FeedExtraction,
    PageExtraction,
)
from old_news.extract.service import extract_feed, judge

SETTINGS = ExtractSettings()

ARTICLE = ("<p>" + "A paragraph with enough words in it to look like prose. " * 12 + "</p>") * 4
TEASER = "<p>Read the rest on our site.</p>"


@db.transactional
async def _readings(session: AsyncSession, version_id: uuid.UUID) -> list[Extraction]:
    rows = await session.execute(
        select(Extraction)
        .where(Extraction.item_version_id == version_id)
        .order_by(Extraction.source)
    )
    return list(rows.scalars().all())


@db.transactional
async def _page_readings(session: AsyncSession, version_id: uuid.UUID) -> int:
    """Child rows for this version, not for the whole table: other articles have them too."""
    return (
        await session.execute(
            select(func.count())
            .select_from(PageExtraction)
            .where(PageExtraction.item_version_id == version_id)
        )
    ).scalar_one()


@db.transactional
async def _page_reading(
    session: AsyncSession, version_id: uuid.UUID, capture_id: uuid.UUID, *, body: str = "Page text."
) -> uuid.UUID:
    reading = PageExtraction(
        item_version_id=version_id,
        page_capture_id=capture_id,
        extractor="test",
        extractor_version="0",
        body=body,
        char_count=len(body),
    )
    session.add(reading)
    await session.flush()
    return reading.id


async def test_feed_text_becomes_a_feed_reading(clean: None, version_id, stored_feed_text):
    """A `FeedExtraction`, which adds no columns — but neither source is the default one,
    and a bare `Extraction` meaning "feed" by omission is the overload this replaces."""
    await stored_feed_text(version_id, ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert type(stored) is FeedExtraction
    assert stored.source == ExtractionSource.FEED
    assert judge(stored.char_count, stored.paragraph_count, SETTINGS) == (True, "")


async def test_a_teaser_is_stored_and_judged_short(clean: None, version_id, stored_feed_text):
    """Most of this corpus is teasers. Knowing which is the point, so the row is kept."""
    await stored_feed_text(version_id, TEASER)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    ok, note = judge(stored.char_count, stored.paragraph_count, SETTINGS)
    assert not ok and note


async def test_the_verdict_follows_the_current_thresholds(
    clean: None, version_id, stored_feed_text
):
    """Asked, never stored. A stored verdict is wrong the moment a threshold moves and
    says nothing about it — 25 of 1058 rows were already in that state."""
    await stored_feed_text(version_id, ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert judge(stored.char_count, stored.paragraph_count, SETTINGS)[0]
    demanding = SETTINGS.model_copy(update={"min_body_chars": stored.char_count + 1})
    assert not judge(stored.char_count, stored.paragraph_count, demanding)[0]


async def test_a_feed_that_carried_nothing_produces_no_row(
    clean: None, version_id, stored_feed_text
):
    await stored_feed_text(version_id, "")

    assert await extract_feed(version_id, SETTINGS) is None


async def test_a_feed_reading_names_its_capture(clean: None, version_id, stored_feed_text):
    """What the child table buys the feed side. It claims nothing else: a fragment has no
    `<head>` to read a claim from, and the feed's own title is on the version."""
    capture_id = await stored_feed_text(version_id, "<h2>Support Bellingcat</h2>" + ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert isinstance(stored, FeedExtraction)
    assert stored.feed_capture_id == capture_id
    assert await _page_readings(version_id) == 0


async def test_both_sources_coexist_for_one_version(
    clean: None, version_id, stored_page, stored_feed_text
):
    """The point of the whole change: two readings of one article, side by side, and the
    discriminator picks the right class for each."""
    await stored_feed_text(version_id, ARTICLE)
    await _page_reading(version_id, await stored_page(version_id, b"<html></html>"))

    await extract_feed(version_id, SETTINGS)

    stored = await _readings(version_id)
    assert [type(row) for row in stored] == [FeedExtraction, PageExtraction]
    assert [row.source for row in stored] == [ExtractionSource.FEED, ExtractionSource.PAGE]


async def test_re_reading_the_same_feed_text_rewrites_its_own_row(
    clean: None, version_id, stored_feed_text
):
    """Idempotent per source, the same way the page path is."""
    await stored_feed_text(version_id, ARTICLE)

    first = await extract_feed(version_id, SETTINGS)
    second = await extract_feed(version_id, SETTINGS)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(await _readings(version_id)) == 1


async def test_deleting_a_reading_takes_its_claims_with_it(clean: None, version_id, stored_page):
    """What the child table buys over a nullable column: binning old extractor output is
    one statement and cannot leave claims behind."""
    reading_id = await _page_reading(version_id, await stored_page(version_id, b"<html></html>"))

    async with db.session() as session:
        await session.execute(text("delete from extractions where id = :id"), {"id": reading_id})

    assert await _page_readings(version_id) == 0


async def test_the_sweep_finds_versions_with_feed_text_and_no_reading(
    clean: None, version_id, stored_feed_text
):
    await stored_feed_text(version_id, ARTICLE)

    assert await extract.due_feed_extractions(50) == [version_id]

    await extract_feed(version_id, SETTINGS)

    assert await extract.due_feed_extractions(50) == []
