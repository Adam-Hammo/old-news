"""Re-encoding a captured image, against the real encoder and a real Postgres."""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import ImageCapture, ImageRendition
from old_news.extract import renditions
from old_news.politeness import ensure

SETTINGS = ExtractSettings()


def _image(width: int, height: int, kind: str, *, frames: int = 1) -> bytes:
    """A photograph-ish image: noise, so the encoder has real work rather than flat colour."""
    from factories import faker

    fake = faker()
    pixels = bytes(fake.random_int(0, 255) for _ in range(width * height * 3))
    made = Image.frombytes("RGB", (width, height), pixels)
    buffer = io.BytesIO()
    if frames > 1:
        # Distinct frames: Pillow collapses identical ones, so appending the same image
        # writes a single-frame file and the animation guard has nothing to catch.
        others = [
            Image.frombytes("RGB", (width, height), bytes(fake.random_int(0, 255) for _ in pixels))
            for _ in range(frames - 1)
        ]
        made.save(buffer, kind, save_all=True, append_images=others)
    else:
        made.save(buffer, kind)
    return buffer.getvalue()


@db.transactional
async def _capture(
    session: AsyncSession, body: bytes, *, content_type: str = "image/png", status: int = 200
) -> uuid.UUID:
    capture = ImageCapture(
        url=f"https://pictures.example.com/{uuid.uuid4()}.png",
        url_digest=uuid.uuid4().bytes,
        host_id=await ensure(session, "pictures.example.com"),
        status=status,
        content_type=content_type,
        body_hash=uuid.uuid4().bytes,
        body=body,
        byte_size=len(body),
    )
    session.add(capture)
    await session.flush()
    return capture.id


@db.transactional
async def _renditions(session: AsyncSession, capture_id: uuid.UUID) -> list[ImageRendition]:
    rows = await session.execute(
        select(ImageRendition).where(ImageRendition.image_capture_id == capture_id)
    )
    return list(rows.scalars().all())


async def test_an_oversized_photograph_is_re_encoded_far_smaller(clean: None):
    """The case that pays for the table: a 2400px PNG hero, which is how two publishers in
    this archive ship every image, at a mean of 1.6 MB each."""
    original = _image(2400, 1200, "PNG")
    capture_id = await _capture(original)

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    assert stored.byte_size < len(original)
    assert stored.width == SETTINGS.rendition_max_width
    assert stored.content_type == "image/avif"
    with Image.open(io.BytesIO(stored.body)) as read_back:
        assert read_back.size == (stored.width, stored.height)


async def test_the_capture_is_left_exactly_as_served(clean: None):
    """The whole bargain: the rendition is derived, so a better encoder re-runs from bytes
    that were never touched."""
    original = _image(1600, 900, "PNG")
    capture_id = await _capture(original)

    await renditions.render_image(capture_id, SETTINGS)

    async with db.session() as session:
        held = (
            await session.execute(select(ImageCapture.body).where(ImageCapture.id == capture_id))
        ).scalar_one()
    assert held == original


async def test_a_jpeg_at_reading_width_is_still_worth_re_encoding(clean: None):
    """Folding JPEG in: 1540 of 1720 captures here are JPEG, and even ones already at
    1200px measured 46-54% smaller as AVIF."""
    original = _image(1200, 675, "JPEG")
    capture_id = await _capture(original, content_type="image/jpeg")

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    assert stored.byte_size < len(original)
    # Not resized, because it is already narrower than the target.
    assert stored.width == 1200


async def test_an_image_nothing_beats_records_that_and_stops_being_due(clean: None):
    """An empty body means "read the capture", and it is what makes the sweep drain. The
    alternative is offering the same image every five minutes for as long as it is held."""
    tiny = _image(8, 8, "PNG")
    capture_id = await _capture(tiny)

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    assert stored.body == b""
    assert stored.byte_size == 0
    assert capture_id not in await extract.due_renditions(SETTINGS, 50)


async def test_an_animation_is_declined_rather_than_flattened(clean: None):
    """Pillow would write the first frame and lose the rest, which is worse than nothing."""
    original = _image(120, 120, "GIF", frames=3)
    capture_id = await _capture(original, content_type="image/gif")

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    assert stored.body == b""


async def test_a_capture_that_will_not_decode_is_not_offered_forever(clean: None):
    """It still gets a row. A sweep that keeps choosing work it cannot do is the failure
    mode `page_captures.outcome` was added to end."""
    capture_id = await _capture(b"not an image at all")

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    assert stored.body == b""
    assert capture_id not in await extract.due_renditions(SETTINGS, 50)


async def test_the_sweep_skips_captures_that_never_answered(clean: None):
    """A 404's body is an error page. Nothing is gained by re-encoding it and the row it
    linked was an article's lead image until the guard went in."""
    error_page = await _capture(b"<html>not found</html>", content_type="text/html", status=404)
    real = await _capture(_image(1600, 900, "PNG"))

    due = await extract.due_renditions(SETTINGS, 50)

    assert real in due
    assert error_page not in due


async def test_a_new_encoder_makes_the_archive_due_again(clean: None, monkeypatch):
    """Same axis as the extractor and the feed parser: bump it and everything re-runs,
    without anything deleting a row."""
    capture_id = await _capture(_image(1600, 900, "PNG"))
    first = await renditions.render_image(capture_id, SETTINGS)
    assert first is not None
    assert capture_id not in await extract.due_renditions(SETTINGS, 50)

    monkeypatch.setattr(renditions, "RULES_REVISION", renditions.RULES_REVISION + 1)

    assert capture_id in await extract.due_renditions(SETTINGS, 50)
    second = await renditions.render_image(capture_id, SETTINGS)
    assert second is not None
    assert second.id != first.id
    assert len(await _renditions(capture_id)) == 2


async def test_re_rendering_the_same_recipe_rewrites_its_own_row(clean: None):
    """Derived and disposable, so the same recipe upserts rather than accumulating."""
    capture_id = await _capture(_image(1600, 900, "PNG"))

    first = await renditions.render_image(capture_id, SETTINGS)
    second = await renditions.render_image(capture_id, SETTINGS)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(await _renditions(capture_id)) == 1


async def test_deleting_a_capture_takes_its_renditions(clean: None):
    """Derived rows must not outlive what they were derived from."""
    capture_id = await _capture(_image(1600, 900, "PNG"))
    await renditions.render_image(capture_id, SETTINGS)

    async with db.session() as session:
        await session.execute(
            update(ImageCapture).where(ImageCapture.id == capture_id).values(body=b"")
        )
        capture = await session.get(ImageCapture, capture_id)
        assert capture is not None
        await session.delete(capture)

    assert await _renditions(capture_id) == []


@pytest.mark.parametrize("width", [400, 1200, 3000])
async def test_the_rendition_never_exceeds_the_reading_width(clean: None, width: int):
    capture_id = await _capture(_image(width, 300, "PNG"))

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    if stored.body:
        assert stored.width <= SETTINGS.rendition_max_width


async def test_a_transparent_image_keeps_its_alpha(clean: None):
    """Found by running this over the real archive: flattening onto RGB turns a logo's
    background black, and Pillow warns about it — which `filterwarnings` makes fatal."""
    made = Image.new("P", (40, 40))
    made.putpalette([0, 0, 0] * 256)
    made.info["transparency"] = 0
    buffer = io.BytesIO()
    made.save(buffer, "PNG")
    capture_id = await _capture(buffer.getvalue())

    stored = await renditions.render_image(capture_id, SETTINGS)

    assert stored is not None
    if stored.body:
        with Image.open(io.BytesIO(stored.body)) as read_back:
            assert read_back.mode in {"RGBA", "LA", "P"}
