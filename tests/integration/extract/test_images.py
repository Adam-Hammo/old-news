"""Image capture: fetched once, kept as received, and only the lead unasked."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import ExtractionImage, ImageCapture, ImageRole
from old_news.extract import images
from old_news.extract.images import capture_image
from old_news.fetch import Fetcher
from old_news.politeness import ensure

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 512
HEADERS = {"Content-Type": "image/png"}


@pytest.fixture
async def fetcher(settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


@pytest.fixture
def cdn(http_server) -> str:
    return http_server(
        {
            "/lead.png": (200, PNG, HEADERS),
            "/script.js": (200, b"alert(1)", {"Content-Type": "application/javascript"}),
            "/gone.png": (404, b"", HEADERS),
        }
    )


@db.transactional
async def _captures(session: AsyncSession) -> list[ImageCapture]:
    rows = await session.execute(select(ImageCapture).order_by(ImageCapture.fetched_at))
    return list(rows.scalars().all())


@db.transactional
async def _linked(session: AsyncSession, slot_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await session.execute(
            select(ExtractionImage.image_capture_id).where(ExtractionImage.id == slot_id)
        )
    ).scalar_one()


async def test_a_lead_image_is_captured_and_linked(
    clean: None, no_policies: None, image_slots, cdn: str, fetcher, settings
):
    """Kept exactly as served: a downscaled rendition is derived later and cannot be undone."""
    slot_id = (await image_slots((f"{cdn}/lead.png", ImageRole.LEAD)))[0]

    stored = await capture_image(slot_id, fetcher, settings)

    assert stored is not None
    assert stored.status == 200
    assert stored.body == PNG
    assert stored.byte_size == len(PNG)
    assert await _linked(slot_id) == stored.id


async def test_one_image_shared_by_two_articles_is_fetched_once(
    clean: None, no_policies: None, image_slots, cdn: str, fetcher, settings
):
    """A publisher's series header appears across dozens of posts."""
    first = (await image_slots((f"{cdn}/lead.png", ImageRole.LEAD)))[0]
    second = (await image_slots((f"{cdn}/lead.png", ImageRole.LEAD)))[0]

    stored = await capture_image(first, fetcher, settings)
    again = await capture_image(second, fetcher, settings)

    assert stored is not None
    # Nothing fetched the second time; the slot was pointed at what was already held.
    assert again is None
    assert len(await _captures()) == 1
    assert await _linked(second) == stored.id


async def test_a_non_image_is_refused_without_being_stored(
    clean: None, no_policies: None, image_slots, cdn: str, fetcher, settings
):
    slot_id = (await image_slots((f"{cdn}/script.js", ImageRole.LEAD)))[0]

    stored = await capture_image(slot_id, fetcher, settings)

    assert stored is not None
    assert stored.body == b""
    assert "javascript" in stored.error
    assert await _linked(slot_id) is None


async def test_a_missing_image_is_recorded_and_leaves_the_slot_empty(
    clean: None, no_policies: None, image_slots, cdn: str, fetcher, settings
):
    slot_id = (await image_slots((f"{cdn}/gone.png", ImageRole.LEAD)))[0]

    stored = await capture_image(slot_id, fetcher, settings)

    assert stored is not None
    assert stored.status == 404
    assert await _linked(slot_id) is None


async def test_only_lead_slots_are_due_unasked(
    clean: None, no_policies: None, image_slots, cdn: str
):
    """The whole reason images are not most of the archive."""
    made = await image_slots(
        (f"{cdn}/lead.png", ImageRole.LEAD), (f"{cdn}/body.png", ImageRole.BODY)
    )

    assert await images.due_images(limit=10) == [made[0]]
    assert await images.due_images(limit=10, role=ImageRole.BODY) == [made[1]]


async def test_a_captured_slot_is_no_longer_due(
    clean: None, no_policies: None, image_slots, cdn: str, fetcher, settings
):
    slot_id = (await image_slots((f"{cdn}/lead.png", ImageRole.LEAD)))[0]

    await capture_image(slot_id, fetcher, settings)

    assert await images.due_images(limit=10) == []


@db.transactional
async def _error_page(session: AsyncSession, url: str) -> uuid.UUID:
    """A capture that answered 404 with an HTML body, which is what a dead CDN link does."""
    capture = ImageCapture(
        url=url,
        url_digest=images.digest_of(url),
        host_id=await ensure(session, "loopback.example.com"),
        status=404,
        content_type="text/html; charset=UTF-8",
        body_hash=b"e" * 32,
        body=b"<html>not found</html>",
        byte_size=22,
    )
    session.add(capture)
    await session.flush()
    return capture.id


async def test_an_error_page_never_satisfies_a_slot(clean: None, image_slots):
    """Twice now. `accept` refuses a body by its type in the fetcher but only below 300, so
    a 404's HTML arrives untyped. The write path stopped taking it and the reuse path went
    on handing the same row back, so the first repair lasted a single sweep."""
    url = "https://loopback.example.com/gone.png"
    (slot_id,) = await image_slots((url, ImageRole.LEAD))
    await _error_page(url)

    assert await images.link_existing(slot_id, url) is None
    assert await _linked(slot_id) is None
