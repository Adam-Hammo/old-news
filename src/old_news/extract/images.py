"""Fetching the images an extraction found.

Eager for the lead — the one image that represents an article, so no surface ever has a
hole in it — and on request for the rest, which is the same task with a different argument
rather than a second mechanism.

Bytes are kept as received. The downscaled rendition a phone wants is derived from these
later; one that replaced them could not be undone.
"""

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, robots
from old_news.config import Settings
from old_news.db import ExtractionImage, ImageCapture, ImageRole
from old_news.fetch import Fetcher, FetchError, Response
from old_news.observability import count, span
from old_news.politeness import ensure, host_of

logger = logging.getLogger(__name__)


def digest_of(url: str) -> bytes:
    return hashlib.sha256(url.encode()).digest()


@db.transactional
async def due_images(
    session: AsyncSession, limit: int, *, role: ImageRole = ImageRole.LEAD
) -> list[uuid.UUID]:
    """Image slots of this role with nothing fetched against them yet."""
    rows = await session.execute(
        select(ExtractionImage.id)
        .where(ExtractionImage.role == role, ExtractionImage.image_capture_id.is_(None))
        .order_by(ExtractionImage.id)
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def hosts_for(session: AsyncSession, slot_ids: list[uuid.UUID]) -> list[str]:
    """The URL behind each slot, in the order given, so the batch can be grouped by host."""
    if not slot_ids:
        return []
    rows = await session.execute(
        select(ExtractionImage.id, ExtractionImage.url).where(ExtractionImage.id.in_(slot_ids))
    )
    urls = dict(rows.all())
    return [urls.get(slot_id, "") for slot_id in slot_ids]


@db.transactional
async def _slot(session: AsyncSession, slot_id: uuid.UUID) -> str | None:
    return (
        await session.execute(select(ExtractionImage.url).where(ExtractionImage.id == slot_id))
    ).scalar_one_or_none()


@db.transactional
async def link_existing(session: AsyncSession, slot_id: uuid.UUID, url: str) -> uuid.UUID | None:
    """Point a slot at a capture already held for its URL, if there is one.

    A publisher's series header appears across dozens of articles. Fetching it once and
    pointing the rest at it is the difference between one copy and dozens.
    """
    held = (
        await session.execute(
            select(ImageCapture.id)
            .where(ImageCapture.url_digest == digest_of(url), ImageCapture.body != b"")
            .limit(1)
        )
    ).scalar_one_or_none()
    if held is not None:
        await session.execute(
            update(ExtractionImage)
            .where(ExtractionImage.id == slot_id)
            .values(image_capture_id=held)
        )
    return held


@db.transactional
async def _store(
    session: AsyncSession,
    slot_id: uuid.UUID,
    url: str,
    *,
    response: Response | None = None,
    error: str = "",
) -> ImageCapture:
    """One row per distinct bytes at a URL, and the slot pointed at it.

    Images are already compressed, so nothing here compresses them again.
    """
    body = response.body if response is not None else b""
    values = {
        "url": url,
        "final_url": response.url if response is not None else "",
        "url_digest": digest_of(url),
        "host_id": await ensure(session, host_of(url)),
        "status": response.status if response is not None else 0,
        "content_type": (response.header("content-type") or "")[:64] if response else "",
        "body_hash": hashlib.sha256(body).digest(),
        "body": body,
        "byte_size": len(body),
        "error": error[:500],
    }
    stored = (
        await session.execute(
            insert(ImageCapture)
            .values(**values)
            # The same bytes at the same URL are one row. Refetching only records that
            # the image was looked at again.
            .on_conflict_do_update(
                index_elements=["url_digest", "body_hash"],
                set_={"fetched_at": func.now()},
            )
            .returning(ImageCapture)
        )
    ).scalar_one()

    if body:
        await session.execute(
            update(ExtractionImage)
            .where(ExtractionImage.id == slot_id)
            .values(image_capture_id=stored.id)
        )
    await session.flush()
    return stored


async def capture_image(
    slot_id: uuid.UUID, fetcher: Fetcher, settings: Settings
) -> ImageCapture | None:
    """Fetch one image slot. Nothing is refetched that is already held."""
    url = await _slot(slot_id)
    if url is None:
        return None

    if await link_existing(slot_id, url) is not None:
        count("extract.images.already_held")
        return None

    attributes: dict[str, Any] = {"image.slot": str(slot_id)}
    with span("capture image", **attributes) as current:
        if not await robots.allows(url, settings):
            current.set_attribute("image.disallowed", True)
            count("extract.images.disallowed", host=host_of(url))
            return None

        try:
            response = await fetcher.get(url, accept=settings.extract.image_content_types)
        except FetchError as exc:
            current.record_exception(exc)
            count("extract.images.failed", host=host_of(url))
            return await _store(slot_id, url, error=str(exc))

        if not await robots.allows_after_redirect(url, response.url, settings):
            current.set_attribute("image.redirect_disallowed", True)
            count("extract.images.redirect_disallowed", host=host_of(response.url))
            return await _store(slot_id, url, error=f"redirected to {host_of(response.url)}")

        count("extract.images.stored" if response.ok else "extract.images.failed")
        return await _store(slot_id, url, response=response)
