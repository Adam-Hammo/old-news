"""Re-encoding a held image in place, against the real encoder and a real Postgres."""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, extract
from old_news.config import ExtractSettings
from old_news.db import ImageCapture
from old_news.extract import encode
from old_news.politeness import ensure

SETTINGS = ExtractSettings()


def _image(width: int, height: int, kind: str, *, frames: int = 1) -> bytes:
    """A photograph-ish image: noise, so the encoder has real work rather than flat colour."""
    from factories import faker

    fake = faker()
    size = width * height * 3
    made = Image.frombytes("RGB", (width, height), fake.random.randbytes(size))
    buffer = io.BytesIO()
    if frames > 1:
        # Distinct frames: Pillow collapses identical ones, so appending the same image
        # writes a single-frame file and the animation guard has nothing to catch.
        others = [
            Image.frombytes("RGB", (width, height), fake.random.randbytes(size))
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
async def _held(session: AsyncSession, capture_id: uuid.UUID) -> ImageCapture:
    return (
        await session.execute(select(ImageCapture).where(ImageCapture.id == capture_id))
    ).scalar_one()


async def test_an_oversized_photograph_is_replaced_by_a_far_smaller_one(clean: None):
    """The case that pays for the sweep: a 2400px PNG hero, which is how two publishers in
    this archive ship every image, at a mean of 1.6 MB each."""
    original = _image(2400, 1200, "PNG")
    capture_id = await _capture(original)

    saved = await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    assert saved > 0
    assert held.byte_size == len(held.body) < len(original)
    assert held.content_type == "image/avif"
    with Image.open(io.BytesIO(held.body)) as read_back:
        assert read_back.size[0] == SETTINGS.image_max_width


async def test_the_hash_still_fingerprints_what_was_served(clean: None):
    """`(url_digest, body_hash)` is what makes one image behind two feeds one fetch. The
    bytes change; the hash has to go on describing what the publisher sent."""
    capture_id = await _capture(_image(2000, 1000, "PNG"))
    before = await _held(capture_id)

    await encode.encode_image(capture_id, SETTINGS)

    after = await _held(capture_id)
    assert after.body != before.body
    assert after.body_hash == before.body_hash


async def test_a_jpeg_at_reading_width_is_still_worth_re_encoding(clean: None):
    """Folding JPEG in: 1540 of 1720 images here are JPEG, and even ones already narrower
    than the target measured 46-54% smaller as AVIF."""
    original = _image(1200, 675, "JPEG")
    capture_id = await _capture(original, content_type="image/jpeg")

    saved = await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    assert saved > 0
    assert len(held.body) < len(original)
    # Not resized, because it is already narrower than the target.
    with Image.open(io.BytesIO(held.body)) as read_back:
        assert read_back.size == (1200, 675)


async def test_an_image_nothing_beats_is_left_exactly_as_served(clean: None):
    """The guard that stops this making things worse — a well-made small PNG, or a WebP,
    re-encodes bigger. It is still stamped, or the sweep offers it forever."""
    tiny = _image(8, 8, "PNG")
    capture_id = await _capture(tiny)

    saved = await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    assert saved == 0
    assert held.body == tiny
    assert held.content_type == "image/png"
    assert held.encoder_version == encode.encoder_version()
    assert capture_id not in await extract.due_encodes(SETTINGS, 50)


async def test_an_animation_is_left_alone_rather_than_flattened(clean: None):
    """Pillow would write the first frame and lose the rest, which is worse than nothing."""
    original = _image(120, 120, "GIF", frames=3)
    capture_id = await _capture(original, content_type="image/gif")

    await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    assert held.body == original


async def test_a_transparent_image_keeps_its_alpha(clean: None):
    """Found by running this over the real archive: flattening onto RGB turns a logo's
    background black, and Pillow warns about it — which `filterwarnings` makes fatal."""
    made = Image.new("P", (40, 40))
    made.putpalette([0, 0, 0] * 256)
    made.info["transparency"] = 0
    buffer = io.BytesIO()
    made.save(buffer, "PNG")
    capture_id = await _capture(buffer.getvalue())

    await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    with Image.open(io.BytesIO(held.body)) as read_back:
        assert read_back.mode in {"RGBA", "LA", "P"}


async def test_an_image_that_will_not_decode_is_not_offered_forever(clean: None):
    """A sweep that keeps choosing work it cannot do is the failure mode
    `page_captures.outcome` was added to end."""
    capture_id = await _capture(b"not an image at all")

    await encode.encode_image(capture_id, SETTINGS)

    assert capture_id not in await extract.due_encodes(SETTINGS, 50)


async def test_the_sweep_skips_images_that_never_answered(clean: None):
    """A 404's body is an error page. Nothing is gained by re-encoding it, and one of them
    was linked as an article's lead image until the guard went in."""
    error_page = await _capture(b"<html>not found</html>", content_type="text/html", status=404)
    real = await _capture(_image(1600, 900, "PNG"))

    due = await extract.due_encodes(SETTINGS, 50)

    assert real in due
    assert error_page not in due


async def test_a_new_encoder_brings_the_archive_back_around(clean: None, monkeypatch):
    """Same axis as the extractor and the feed parser. Unlike those it cannot re-derive
    from the original, so what it re-reads is the last form kept."""
    capture_id = await _capture(_image(2000, 1000, "PNG"))
    await encode.encode_image(capture_id, SETTINGS)
    assert capture_id not in await extract.due_encodes(SETTINGS, 50)

    monkeypatch.setattr(encode, "RULES_REVISION", encode.RULES_REVISION + 1)

    assert capture_id in await extract.due_encodes(SETTINGS, 50)


async def test_a_wider_target_brings_it_back_around_too(clean: None):
    """`spec` is half the stamp, so changing the width is a re-read and not a silent
    mismatch between what is configured and what is held."""
    capture_id = await _capture(_image(2000, 1000, "PNG"))
    await encode.encode_image(capture_id, SETTINGS)

    wider = SETTINGS.model_copy(update={"image_max_width": SETTINGS.image_max_width + 400})

    assert capture_id in await extract.due_encodes(wider, 50)


async def test_running_twice_does_not_spend_a_second_generation(clean: None):
    """AVIF re-encoded at the same quality is smaller again, so the size guard does not
    catch this — only the stamp does. With no original to fall back on, a retried job
    would quietly degrade the picture it already wrote."""
    capture_id = await _capture(_image(2000, 1000, "PNG"))
    assert await encode.encode_image(capture_id, SETTINGS) > 0
    once = await _held(capture_id)

    assert await encode.encode_image(capture_id, SETTINGS) == 0

    twice = await _held(capture_id)
    assert twice.body == once.body


@pytest.mark.parametrize("width", [400, 1600, 3000])
async def test_what_is_held_never_exceeds_the_reading_width(clean: None, width: int):
    capture_id = await _capture(_image(width, 300, "PNG"))

    await encode.encode_image(capture_id, SETTINGS)

    held = await _held(capture_id)
    with Image.open(io.BytesIO(held.body)) as read_back:
        assert read_back.size[0] <= max(width, SETTINGS.image_max_width)
