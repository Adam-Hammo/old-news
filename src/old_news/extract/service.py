"""Turning a captured artefact into something readable. Head versions only."""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import (
    READING_IDENTITY,
    READING_KEY,
    Extraction,
    ExtractionImage,
    ExtractionSource,
    FeedExtraction,
    ItemVersion,
    PageCapture,
    PageExtraction,
    dictionaries,
)
from old_news.extract import article
from old_news.observability import count, span

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Pending:
    """An artefact waiting to be read, and the capture row it came out of."""

    version_id: uuid.UUID
    source: ExtractionSource
    capture_id: uuid.UUID
    body: bytes
    final_url: str


def _extracted(source: ExtractionSource):
    """Versions the current extractor has already read from this kind of artefact."""
    return (
        select(Extraction.item_version_id)
        .where(
            Extraction.source == source,
            Extraction.extractor == article.EXTRACTOR,
            Extraction.extractor_version == article.extractor_version(),
        )
        .scalar_subquery()
    )


@db.transactional
async def due_extractions(
    session: AsyncSession, settings: ExtractSettings, limit: int
) -> list[uuid.UUID]:
    """Head versions with a successful capture and no output from the current extractor."""
    done = _extracted(ExtractionSource.PAGE)
    rows = await session.execute(
        select(ItemVersion.id)
        .join(PageCapture, PageCapture.item_version_id == ItemVersion.id)
        .where(
            PageCapture.succeeded,
            PageCapture.body != b"",
            ItemVersion.is_head,
            ItemVersion.id.not_in(done),
        )
        .distinct()
        .order_by(ItemVersion.id)
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def due_feed_extractions(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Head versions whose captured feed text the current extractor has not read."""
    done = _extracted(ExtractionSource.FEED)
    rows = await session.execute(
        select(ItemVersion.id)
        .where(ItemVersion.is_head, ItemVersion.id.not_in(done), ItemVersion.has_feed_text)
        .order_by(ItemVersion.observed_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def pending_feed(session: AsyncSession, version_id: uuid.UUID) -> Pending | None:
    """The version's newest feed capture, expanded. None when the feed carried no text."""
    version = (
        await session.execute(
            select(ItemVersion)
            .where(ItemVersion.id == version_id)
            .options(joinedload(ItemVersion.feed_capture))
        )
    ).scalar_one_or_none()
    if version is None or version.feed_capture is None or not version.feed_capture.body:
        return None

    capture = version.feed_capture
    return Pending(
        version_id=version_id,
        source=ExtractionSource.FEED,
        capture_id=capture.id,
        body=await dictionaries.expand(session, capture.body),
        # Relative links in feed content resolve against the article, not the feed.
        final_url=version.canonical_url or version.url,
    )


@db.transactional
async def pending(session: AsyncSession, version_id: uuid.UUID) -> Pending | None:
    """The version's latest successful capture, expanded. None when there is none."""
    version = (
        await session.execute(
            select(ItemVersion)
            .where(ItemVersion.id == version_id)
            .options(joinedload(ItemVersion.latest_capture))
        )
    ).scalar_one_or_none()
    if version is None or version.latest_capture is None or not version.latest_capture.body:
        return None

    capture = version.latest_capture
    return Pending(
        version_id=version_id,
        source=ExtractionSource.PAGE,
        capture_id=capture.id,
        body=await dictionaries.expand(session, capture.body),
        final_url=capture.final_url or capture.url,
    )


def _artefact(
    found: Pending, parsed: article.Article, reading_id: uuid.UUID
) -> tuple[type[Extraction], dict[str, object]]:
    """The half of a reading only one kind of artefact has, and where it goes."""
    if found.source == ExtractionSource.PAGE:
        return PageExtraction, {
            "id": reading_id,
            "page_capture_id": found.capture_id,
            "title": parsed.title,
            "byline": parsed.byline,
            "language": parsed.language[:32],
            "site_name": parsed.site_name,
            "page_type": parsed.page_type[:32],
            "published_claim": parsed.published_claim[:32],
        }
    # A fragment has no head to claim anything, so the capture is all there is to name.
    return FeedExtraction, {"id": reading_id, "feed_capture_id": found.capture_id}


@db.transactional
async def store(session: AsyncSession, found: Pending, parsed: article.Article) -> Extraction:
    """Insert a reading, and the half of it only its own kind of artefact has."""
    base = {
        "item_version_id": found.version_id,
        "source": found.source,
        "extractor": article.EXTRACTOR,
        "extractor_version": article.extractor_version(),
        "body": parsed.body,
        "links": [{"url": link.url, "anchor": link.anchor} for link in parsed.links],
        "char_count": parsed.char_count,
        "paragraph_count": parsed.paragraph_count,
        "link_density": parsed.link_density,
    }
    # `insert(Model)` targets that model's own table, which is what each half needs.
    reading_id = (
        await session.execute(
            insert(Extraction)
            .values(**base)
            .on_conflict_do_update(
                constraint=READING_KEY,
                set_={key: base[key] for key in base if key not in READING_IDENTITY},
            )
            .returning(Extraction.id)
        )
    ).scalar_one()

    child, values = _artefact(found, parsed, reading_id)
    await session.execute(
        insert(child)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["id"], set_={key: values[key] for key in values if key != "id"}
        )
    )

    for position, image in enumerate(parsed.images):
        await session.execute(
            insert(ExtractionImage)
            .values(
                extraction_id=reading_id,
                url=image.url,
                role=image.role,
                alt=image.alt[:2000],
                position=position,
            )
            .on_conflict_do_nothing(index_elements=["extraction_id", "url"])
        )

    await session.flush()
    return await session.get_one(Extraction, reading_id)


def judge(chars: int, paragraphs: int, settings: ExtractSettings) -> tuple[bool, str]:
    """Whether this reads like an article. Asked, never stored — the thresholds move."""
    if not chars:
        return False, "nothing extracted"
    if chars < settings.min_body_chars:
        return False, f"only {chars} characters"
    if paragraphs < settings.min_paragraphs:
        return False, f"only {paragraphs} paragraphs"
    return True, ""


async def extract_page(version_id: uuid.UUID, settings: ExtractSettings) -> Extraction | None:
    """Read a stored page. Parsing happens outside any transaction."""
    found = await pending(version_id)
    if found is None:
        return None

    attributes: dict[str, Any] = {"version.id": str(version_id)}
    with span("extract page", **attributes) as current:
        parsed = article.parse(found.body.decode("utf-8", errors="replace"), found.final_url)
        current.set_attribute("extract.chars", parsed.char_count)

        ok, note = judge(parsed.char_count, parsed.paragraph_count, settings)
        stored = await store(found, parsed)
        current.set_attribute("extract.ok", ok)
        count("extract.extractions.ok" if ok else "extract.extractions.poor")
        if not ok:
            logger.warning("poor extraction for version %s: %s", version_id, note)
        return stored


async def extract_feed(version_id: uuid.UUID, settings: ExtractSettings) -> Extraction | None:
    """Read the text the feed already gave us. Nothing to fail but the parse."""
    found = await pending_feed(version_id)
    if found is None:
        return None

    attributes: dict[str, Any] = {"version.id": str(version_id)}
    with span("extract feed", **attributes) as current:
        parsed = article.parse_fragment(
            found.body.decode("utf-8", errors="replace"), found.final_url
        )
        current.set_attribute("extract.chars", parsed.char_count)

        ok, _ = judge(parsed.char_count, parsed.paragraph_count, settings)
        stored = await store(found, parsed)
        current.set_attribute("extract.ok", ok)
        # A teaser is not a defect, so no warning here as there is for a bad page.
        count("extract.feed_extractions.ok" if ok else "extract.feed_extractions.teaser")
        return stored
