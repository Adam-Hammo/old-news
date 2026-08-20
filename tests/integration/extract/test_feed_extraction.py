"""Reading the text a feed already gave us, as a base row beside a page's child row."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import (
    Extraction,
    ExtractionSource,
    FeedExtraction,
    ItemVersion,
    PageExtraction,
)
from old_news.extract.service import extract_feed, judge

SETTINGS = ExtractSettings()

ARTICLE = ("<p>" + "A paragraph with enough words in it to look like prose. " * 12 + "</p>") * 4
TEASER = "<p>Read the rest on our site.</p>"


@db.transactional
async def _set_content(session: AsyncSession, version_id: uuid.UUID, content: str) -> None:
    version = await session.get(ItemVersion, version_id)
    assert version is not None
    version.content = content


@db.transactional
async def _readings(session: AsyncSession, version_id: uuid.UUID) -> list[Extraction]:
    rows = await session.execute(
        select(Extraction)
        .where(Extraction.item_version_id == version_id)
        .order_by(Extraction.source)
    )
    return list(rows.scalars().all())


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


async def test_feed_text_becomes_a_feed_reading(clean: None, feed_id, article):
    """A `FeedExtraction`, which adds no columns — but neither source is the default one,
    and a bare `Extraction` meaning "feed" by omission is the overload this replaces."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert type(stored) is FeedExtraction
    assert stored.source == ExtractionSource.FEED
    assert judge(stored.char_count, stored.paragraph_count, SETTINGS) == (True, "")


async def test_a_teaser_is_stored_and_judged_short(clean: None, feed_id, article):
    """Most of this corpus is teasers. Knowing which is the point, so the row is kept."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, TEASER)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    ok, note = judge(stored.char_count, stored.paragraph_count, SETTINGS)
    assert not ok and note


async def test_the_verdict_follows_the_current_thresholds(clean: None, feed_id, article):
    """Asked, never stored. A stored verdict is wrong the moment a threshold moves and
    says nothing about it — 25 of 1058 rows were already in that state."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    stored = await extract_feed(version_id, SETTINGS)

    assert stored is not None
    assert judge(stored.char_count, stored.paragraph_count, SETTINGS)[0]
    demanding = SETTINGS.model_copy(update={"min_body_chars": stored.char_count + 1})
    assert not judge(stored.char_count, stored.paragraph_count, demanding)[0]


async def test_a_feed_that_carried_nothing_produces_no_row(clean: None, feed_id, article):
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, "")

    assert await extract_feed(version_id, SETTINGS) is None


async def test_a_feed_reading_has_no_child_row(clean: None, feed_id, article):
    """A fragment has no `<head>` to claim anything, and the feed's own title is on the version."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, "<h2>Support Bellingcat</h2>" + ARTICLE)

    await extract_feed(version_id, SETTINGS)

    async with db.session() as session:
        assert (
            await session.execute(select(func.count()).select_from(PageExtraction.__table__))
        ).scalar_one() == 0


async def test_both_sources_coexist_for_one_version(clean: None, feed_id, article, stored_page):
    """The point of the whole change: two readings of one article, side by side, and the
    discriminator picks the right class for each."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)
    await _page_reading(version_id, await stored_page(version_id, b"<html></html>"))

    await extract_feed(version_id, SETTINGS)

    stored = await _readings(version_id)
    assert [type(row) for row in stored] == [FeedExtraction, PageExtraction]
    assert [row.source for row in stored] == [ExtractionSource.FEED, ExtractionSource.PAGE]


async def test_re_reading_the_same_feed_text_rewrites_its_own_row(clean: None, feed_id, article):
    """Idempotent per source, the same way the page path is."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    first = await extract_feed(version_id, SETTINGS)
    second = await extract_feed(version_id, SETTINGS)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(await _readings(version_id)) == 1


async def test_deleting_a_reading_takes_its_claims_with_it(
    clean: None, feed_id, article, stored_page
):
    """What the child table buys over a nullable column: binning old extractor output is
    one statement and cannot leave claims behind."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    reading_id = await _page_reading(version_id, await stored_page(version_id, b"<html></html>"))

    async with db.session() as session:
        await session.execute(text("delete from extractions where id = :id"), {"id": reading_id})

    async with db.session() as session:
        assert (
            await session.execute(select(func.count()).select_from(PageExtraction.__table__))
        ).scalar_one() == 0


async def test_the_feed_page_ratio_is_a_join(clean: None, feed_id, article, stored_page):
    """`feed_body_ratio` was a column only because the feed reading was not a row. Both
    are rows, so the comparison is a join and cannot go stale against either side."""
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)
    await extract_feed(version_id, SETTINGS)
    await _page_reading(
        version_id, await stored_page(version_id, b"<html></html>"), body="x" * 4000
    )

    feed, page = (Extraction.__table__.alias("f"), Extraction.__table__.alias("p"))
    async with db.session() as session:
        ratio = (
            await session.execute(
                select(page.c.char_count / func.nullif(feed.c.char_count, 0))
                .select_from(feed.join(page, feed.c.item_version_id == page.c.item_version_id))
                .where(
                    feed.c.source == ExtractionSource.FEED, page.c.source == ExtractionSource.PAGE
                )
            )
        ).scalar_one()

    assert ratio is not None and ratio > 0


async def test_the_sweep_finds_versions_with_feed_text_and_no_reading(
    clean: None, feed_id, article
):
    version_id = (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]
    await _set_content(version_id, ARTICLE)

    assert await extract.due_feed_extractions(50) == [version_id]

    await extract_feed(version_id, SETTINGS)

    assert await extract.due_feed_extractions(50) == []
