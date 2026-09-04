"""Which body images get held, which is a question about the tier, not the picture."""

import datetime
import io
import uuid

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import Extraction, ExtractionImage, ImageCapture, ImageRole, ItemVersion, Tier
from old_news.extract import images
from old_news.politeness import ensure

DAY = datetime.timedelta(days=1)
LIMIT = 50


@db.transactional
async def _slot(session: AsyncSession, item_id: uuid.UUID, url: str, role: str) -> uuid.UUID:
    """An image an extraction found and nothing has fetched."""
    extraction_id = await session.scalar(
        select(Extraction.id)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
        .where(ItemVersion.item_id == item_id)
    )
    slot = ExtractionImage(extraction_id=extraction_id, url=url, role=role)
    session.add(slot)
    await session.flush()
    return slot.id


@db.transactional
async def _held(session: AsyncSession, url: str) -> None:
    """A usable capture for a URL, drawn rather than fetched."""
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 10, 10)).save(buffer, "PNG")
    body = buffer.getvalue()
    session.add(
        ImageCapture(
            url=url,
            url_digest=images.digest_of(url),
            host_id=await ensure(session, "cdn.example.com"),
            status=200,
            content_type="image/png",
            body_hash=uuid.uuid4().bytes,
            body=body,
            byte_size=len(body),
        )
    )


async def _due() -> list[uuid.UUID]:
    return await images.due_body_images(LIMIT)


async def test_an_archive_feed_has_its_body_images_held(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.ARCHIVE)
    item_id = await story(feed_id, "An essay", body="Text.")
    slot = await _slot(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    assert await _due() == [slot]


async def test_a_kindle_feed_does_too(clean: None, feed, story):
    """The tiers nest: kindle takes everything archive does."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    item_id = await story(feed_id, "An essay", body="Text.")
    slot = await _slot(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    assert await _due() == [slot]


async def test_the_wire_does_not(clean: None, feed, story):
    """Measured, the wire is about 88% of the ongoing bill and none of what is read twice."""
    feed_id = await feed("wire.example.com")
    item_id = await story(feed_id, "A dispatch", body="Text.")
    await _slot(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    assert await _due() == []


async def test_a_long_window_alone_is_not_enough(clean: None, feed, story):
    """The window says how long to show it; the tier says how much of it to hold."""
    feed_id = await feed("wire.example.com", expires_after=180 * DAY)
    item_id = await story(feed_id, "A dispatch", body="Text.")
    await _slot(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    assert await _due() == []


async def test_a_dropped_subscription_does_not(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.ARCHIVE, active=False)
    item_id = await story(feed_id, "An essay", body="Text.")
    await _slot(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    assert await _due() == []


async def test_a_lead_is_not_offered_by_the_body_sweep(clean: None, feed, story):
    """Leads have their own sweep, and it asks whatever the tier."""
    feed_id = await feed("kept.example.com", tier=Tier.ARCHIVE)
    item_id = await story(feed_id, "An essay", body="Text.")
    lead = await _slot(item_id, "https://cdn.example.com/hero.png", ImageRole.LEAD)

    assert lead not in await _due()
    assert await images.due_images(LIMIT) == [lead]


async def test_the_wires_lead_is_still_fetched(clean: None, feed, story):
    """A card or a page with a hole in it is a different problem from an image bill."""
    item_id = await story(await feed("wire.example.com"), "A dispatch", body="Text.")
    lead = await _slot(item_id, "https://cdn.example.com/hero.png", ImageRole.LEAD)

    assert await images.due_images(LIMIT) == [lead]


async def test_a_slot_already_fetched_is_not_offered_again(clean: None, feed, story):
    url = "https://cdn.example.com/a.png"
    feed_id = await feed("kept.example.com", tier=Tier.ARCHIVE)
    item_id = await story(feed_id, "An essay", body="Text.")
    slot = await _slot(item_id, url, ImageRole.BODY)
    assert await _due() == [slot]

    await _held(url)
    await images.link_existing(slot, url)

    assert await _due() == []


async def test_the_newest_pictures_are_asked_for_first(clean: None, feed, story):
    """A fresh article's images are still up; a year-old one's are gone or stable."""
    feed_id = await feed("kept.example.com", tier=Tier.ARCHIVE)
    first = await story(feed_id, "Older", body="Text.")
    second = await story(feed_id, "Newer", body="Text.")
    older = await _slot(first, "https://cdn.example.com/a.png", ImageRole.BODY)
    newer = await _slot(second, "https://cdn.example.com/b.png", ImageRole.BODY)

    assert await _due() == [newer, older]
