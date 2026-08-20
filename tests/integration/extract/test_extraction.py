"""Extraction against a real Postgres, from a real captured page."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import Extraction, ExtractionImage, ImageRole, PageExtraction
from old_news.extract import article as article_module
from old_news.extract.service import extract_page, judge

GUARDIAN_URL = "https://www.theguardian.com/society/2026/aug/19/benefits-disabled-young-people"

SETTINGS = ExtractSettings()


@db.transactional
async def _images(session: AsyncSession, extraction_id: uuid.UUID) -> list[ExtractionImage]:
    rows = await session.execute(
        select(ExtractionImage)
        .where(ExtractionImage.extraction_id == extraction_id)
        .order_by(ExtractionImage.position)
    )
    return list(rows.scalars().all())


@db.transactional
async def _count(session: AsyncSession, version_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(Extraction.id).where(Extraction.item_version_id == version_id)
    )
    return len(rows.all())


async def _captured(feed_id: uuid.UUID, build, page, stored_page) -> uuid.UUID:
    """A head version with a real Guardian page stored against it."""
    version_id = (await build(feed_id, ("An article", GUARDIAN_URL)))[0]
    await stored_page(version_id, page("guardian-article.html").encode())
    return version_id


async def test_a_captured_page_becomes_a_readable_extraction(
    clean: None, feed_id, article, page, stored_page
):
    version_id = await _captured(feed_id, article, page, stored_page)

    stored = await extract_page(version_id, SETTINGS)

    assert stored is not None
    assert isinstance(stored, PageExtraction)
    assert judge(stored.char_count, stored.paragraph_count, SETTINGS) == (True, "")
    assert stored.char_count > 3000
    assert stored.site_name == "The Guardian"
    assert stored.extractor == article_module.EXTRACTOR
    assert len(stored.links) > 1


async def test_the_lead_image_gets_a_row(clean: None, feed_id, article, page, stored_page):
    """A row rather than JSONB, because it is what a capture attaches to."""
    version_id = await _captured(feed_id, article, page, stored_page)

    stored = await extract_page(version_id, SETTINGS)

    assert stored is not None
    images = await _images(stored.id)
    assert [image.role for image in images][:1] == [ImageRole.LEAD]
    assert images[0].url.startswith("http")


async def test_re_extracting_with_the_same_extractor_rewrites_one_row(
    clean: None, feed_id, article, page, stored_page
):
    """Idempotent, so a repeated sweep cannot pile up duplicates."""
    version_id = await _captured(feed_id, article, page, stored_page)

    first = await extract_page(version_id, SETTINGS)
    second = await extract_page(version_id, SETTINGS)

    assert first is not None and second is not None
    assert first.id == second.id
    assert await _count(version_id) == 1


async def test_a_version_with_no_capture_extracts_nothing(
    clean: None, feed_id, article, page, stored_page
):
    version_id = (await article(feed_id, ("An article", GUARDIAN_URL)))[0]

    assert await extract_page(version_id, SETTINGS) is None


async def test_a_captured_page_is_due_until_it_is_extracted(
    clean: None, feed_id, article, page, stored_page
):
    version_id = await _captured(feed_id, article, page, stored_page)

    assert await extract.due_extractions(SETTINGS, limit=10) == [version_id]
    await extract_page(version_id, SETTINGS)
    assert await extract.due_extractions(SETTINGS, limit=10) == []


async def test_a_new_extractor_version_makes_the_archive_due_again(
    clean: None, feed_id, article, page, stored_page, monkeypatch
):
    """Bumping the extractor re-runs the corpus without anything deleting a row."""
    version_id = await _captured(feed_id, article, page, stored_page)
    await extract_page(version_id, SETTINGS)

    assert await extract.due_extractions(SETTINGS, limit=10) == []

    monkeypatch.setattr(article_module, "RULES_REVISION", article_module.RULES_REVISION + 1)

    # The whole corpus comes back, which is the point — so this asks about its own row.
    assert version_id in await extract.due_extractions(SETTINGS, limit=10)
