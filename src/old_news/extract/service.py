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
    Extraction,
    ExtractionImage,
    ExtractionSource,
    ItemVersion,
    PageCapture,
    dictionaries,
)
from old_news.extract import article
from old_news.observability import count, span

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Pending:
    """An artefact waiting to be read, with what the feed said for comparison.

    `capture_id` is None for a feed-sourced extraction: what it reads is the document
    behind the version, which the version already names.
    """

    version_id: uuid.UUID
    source: ExtractionSource
    body: bytes
    final_url: str
    feed_body_chars: int
    capture_id: uuid.UUID | None = None


@db.transactional
async def due_extractions(
    session: AsyncSession, settings: ExtractSettings, limit: int
) -> list[uuid.UUID]:
    """Head versions with a successful capture and no output from the current extractor.

    Keyed on the extractor version, so bumping it makes the whole archive due again
    without anything deleting a row.
    """
    done = (
        select(Extraction.item_version_id)
        .where(
            Extraction.source == ExtractionSource.PAGE,
            Extraction.extractor == article.EXTRACTOR,
            Extraction.extractor_version == article.extractor_version(),
        )
        .scalar_subquery()
    )
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
    """Head versions whose feed text has not been read by the current extractor.

    No capture needed, no network, and nothing to wait for: the bytes arrived with the
    poll. So this runs ahead of capture rather than behind it, and every article has
    something readable from the moment it is first seen.
    """
    done = (
        select(Extraction.item_version_id)
        .where(
            Extraction.source == ExtractionSource.FEED,
            Extraction.extractor == article.EXTRACTOR,
            Extraction.extractor_version == article.extractor_version(),
        )
        .scalar_subquery()
    )
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
    """The version's own feed text, ready to read. None when the feed carried none."""
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
        feed_body_chars=len(row.content),
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
        feed_body_chars=len(version.feed_body),
    )


@db.transactional
async def store(
    session: AsyncSession,
    found: Pending,
    parsed: article.Article,
    settings: ExtractSettings,
) -> Extraction:
    """Insert an extraction and its image slots.

    Re-running the same extractor over the same version writes the same row rather than a
    second one; a new extractor version lands alongside and neither replaces the other.
    """
    ratio = parsed.char_count / found.feed_body_chars if found.feed_body_chars else 0.0
    ok, note = _judge(parsed, settings)

    values = {
        "item_version_id": found.version_id,
        "source": found.source,
        "page_capture_id": found.capture_id,
        "extractor": article.EXTRACTOR,
        "extractor_version": article.extractor_version(),
        "body": parsed.body,
        "title": parsed.title,
        "byline": parsed.byline,
        "language": parsed.language[:32],
        "site_name": parsed.site_name,
        "page_type": parsed.page_type[:32],
        "published_claim": parsed.published_claim[:32],
        "links": [{"url": link.url, "anchor": link.anchor} for link in parsed.links],
        "char_count": parsed.char_count,
        "paragraph_count": parsed.paragraph_count,
        "link_density": parsed.link_density,
        "feed_body_ratio": round(ratio, 4),
        "ok": ok,
        "note": note,
    }
    stored = (
        await session.execute(
            insert(Extraction)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["item_version_id", "source", "extractor", "extractor_version"],
                set_={key: values[key] for key in values if key != "item_version_id"},
            )
            .returning(Extraction)
        )
    ).scalar_one()

    for position, image in enumerate(parsed.images):
        await session.execute(
            insert(ExtractionImage)
            .values(
                extraction_id=stored.id,
                url=image.url,
                role=image.role,
                alt=image.alt[:2000],
                position=position,
            )
            .on_conflict_do_nothing(index_elements=["extraction_id", "url"])
        )

    await session.flush()
    return stored


def _judge(parsed: article.Article, settings: ExtractSettings) -> tuple[bool, str]:
    """Whether this looks like an article. Measured against real pages and a consent wall.

    Never destructive: a row that fails is still stored, because the judgement is the
    thing most likely to be wrong.
    """
    if not parsed.body:
        return False, "nothing extracted"
    if parsed.char_count < settings.min_body_chars:
        return False, f"only {parsed.char_count} characters"
    if parsed.paragraph_count < settings.min_paragraphs:
        return False, f"only {parsed.paragraph_count} paragraphs"
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

        stored = await store(found, parsed, settings)
        current.set_attribute("extract.ok", stored.ok)
        count("extract.extractions.ok" if stored.ok else "extract.extractions.poor")
        if not stored.ok:
            logger.warning("poor extraction for version %s: %s", version_id, stored.note)
        return stored


async def extract_feed(version_id: uuid.UUID, settings: ExtractSettings) -> Extraction | None:
    """Read the text the feed already gave us. No network, so nothing to fail but parsing."""
    found = await pending_feed(version_id)
    if found is None:
        return None

    attributes: dict[str, Any] = {"version.id": str(version_id)}
    with span("extract feed", **attributes) as current:
        parsed = article.parse_fragment(
            found.body.decode("utf-8", errors="replace"), found.final_url
        )
        current.set_attribute("extract.chars", parsed.char_count)

        stored = await store(found, parsed, settings)
        current.set_attribute("extract.ok", stored.ok)
        # A teaser is not a defect — most of this corpus is teasers, and knowing which is
        # the point. So no warning here, unlike a page that came back unreadable.
        count("extract.feed_extractions.ok" if stored.ok else "extract.feed_extractions.teaser")
        return stored
