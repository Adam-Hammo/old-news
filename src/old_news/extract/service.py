"""Turning a captured page into something readable.

Capture is per settled version; extraction runs on head versions only, because superseded
text is not what anyone reads. Re-extraction is a separate concern from re-capture and runs
down this same path.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
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
    """An artefact waiting to be read. `capture_id` is None for a feed reading."""

    version_id: uuid.UUID
    source: ExtractionSource
    body: bytes
    final_url: str
    capture_id: uuid.UUID | None = None


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
    """Head versions with a successful capture and no output from the current extractor.

    Keyed on the extractor version, so bumping it makes the whole archive due again
    without anything deleting a row.
    """
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
    """Head versions whose feed text the current extractor has not read.

    No capture, no network, nothing to wait for — so this runs ahead of capture.
    """
    done = _extracted(ExtractionSource.FEED)
    rows = await session.execute(
        select(ItemVersion.id)
        .where(
            ItemVersion.is_head,
            ItemVersion.id.not_in(done),
            func.length(ItemVersion.content) > 0,
        )
        .order_by(ItemVersion.observed_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def pending_feed(session: AsyncSession, version_id: uuid.UUID) -> Pending | None:
    """The version's own feed text. None when the feed carried none."""
    row = (
        await session.execute(
            select(ItemVersion.content, ItemVersion.url, ItemVersion.canonical_url).where(
                ItemVersion.id == version_id
            )
        )
    ).first()
    if row is None or not row.content:
        return None

    return Pending(
        version_id=version_id,
        source=ExtractionSource.FEED,
        body=row.content.encode(),
        # Relative links in feed content resolve against the article, not the feed.
        final_url=row.canonical_url or row.url,
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


@db.transactional
async def store(session: AsyncSession, found: Pending, parsed: article.Article) -> Extraction:
    """Insert a reading and, for a page, what that page claimed about itself.

    Two statements because it is two tables. Re-reading the same way rewrites both.
    """
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
    # `insert(Model)` targets that model's own table, which for a hierarchy is what
    # each half of this needs.
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

    if found.source == ExtractionSource.PAGE:
        claims = {
            "id": reading_id,
            "page_capture_id": found.capture_id,
            "title": parsed.title,
            "byline": parsed.byline,
            "language": parsed.language[:32],
            "site_name": parsed.site_name,
            "page_type": parsed.page_type[:32],
            "published_claim": parsed.published_claim[:32],
        }
        await session.execute(
            insert(PageExtraction)
            .values(**claims)
            .on_conflict_do_update(
                index_elements=["id"], set_={key: claims[key] for key in claims if key != "id"}
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
    """Whether this reads like an article. Measured against real pages and a consent wall.

    Takes the measurements rather than the thing measured, so a parse in flight and a row
    read back are the same call. Asked, never stored: the thresholds live in config, so a
    stored verdict goes wrong silently. Failing is never destructive either way.
    """
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
        # A teaser is not a defect — most of this corpus is teasers, and knowing which is
        # the point. So no warning here, unlike a page that came back unreadable.
        count("extract.feed_extractions.ok" if ok else "extract.feed_extractions.teaser")
        return stored
