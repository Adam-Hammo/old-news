"""The Pillow boundary. Re-encoding a captured image for reading, never over the original."""

import io
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import PIL
from PIL import Image
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import RENDITION_IDENTITY, RENDITION_KEY, ImageCapture, ImageRendition
from old_news.observability import count, span

logger = logging.getLogger(__name__)

# Bumped when anything below changes what comes out, so old renditions stay attributable
# and the sweep offers the archive again.
RULES_REVISION = 1

# What a phone actually renders. Anything already narrower is re-encoded but not resized.
CONTENT_TYPE = "image/avif"


def encoder_version() -> str:
    return f"{PIL.__version__}+{RULES_REVISION}"


def spec(settings: ExtractSettings) -> str:
    """The recipe, as it is stored: format and the width it was asked to fit."""
    return f"avif-{settings.rendition_max_width}"


@dataclass(frozen=True, slots=True)
class Rendered:
    """What came out, or nothing when the capture was already the better form."""

    body: bytes
    width: int
    height: int


@db.transactional
async def due_renditions(
    session: AsyncSession, settings: ExtractSettings, limit: int
) -> list[uuid.UUID]:
    """Captures that answered with bytes and have no rendition from the current encoder."""
    rendered = exists(
        select(ImageRendition.id).where(
            ImageRendition.image_capture_id == ImageCapture.id,
            ImageRendition.spec == spec(settings),
            ImageRendition.encoder_version == encoder_version(),
        )
    )
    rows = await session.execute(
        select(ImageCapture.id)
        .where(
            ImageCapture.status.between(200, 299),
            ImageCapture.body != b"",
            ImageCapture.content_type.startswith("image/"),
            ~rendered,
        )
        # Biggest first: the whole point is the ones costing the most.
        .order_by(ImageCapture.byte_size.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def _captured(session: AsyncSession, capture_id: uuid.UUID) -> bytes | None:
    return (
        await session.execute(select(ImageCapture.body).where(ImageCapture.id == capture_id))
    ).scalar_one_or_none()


def render(body: bytes, settings: ExtractSettings) -> Rendered | None:
    """Re-encode one image at reading width. None when the capture already wins."""
    # Outside a transaction: tens of milliseconds of CPU per image.
    with Image.open(io.BytesIO(body)) as opened:
        # Animation would be flattened to its first frame, which is worse than declining.
        if getattr(opened, "n_frames", 1) > 1:
            return None

        width, height = opened.size
        limit = settings.rendition_max_width
        # AVIF carries alpha, and flattening a transparent logo onto RGB turns its
        # background black. Pillow warns about it, which `filterwarnings` makes fatal.
        transparent = opened.mode in {"RGBA", "LA", "PA"} or "transparency" in opened.info
        source = opened.convert("RGBA" if transparent else "RGB")
        if width > limit:
            source = source.resize((limit, round(height * limit / width)), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        source.save(buffer, "AVIF", quality=settings.rendition_quality)

    encoded = buffer.getvalue()
    if len(encoded) >= len(body):
        return None
    return Rendered(encoded, source.size[0], source.size[1])


@db.transactional
async def _store(
    session: AsyncSession,
    capture_id: uuid.UUID,
    rendered: Rendered | None,
    settings: ExtractSettings,
) -> ImageRendition:
    """One row per capture and recipe, whether or not the re-encode won."""
    values = {
        "image_capture_id": capture_id,
        "spec": spec(settings),
        "encoder_version": encoder_version(),
        "content_type": CONTENT_TYPE if rendered else "",
        "body": rendered.body if rendered else b"",
        "byte_size": len(rendered.body) if rendered else 0,
        "width": rendered.width if rendered else 0,
        "height": rendered.height if rendered else 0,
    }
    stored = (
        await session.execute(
            insert(ImageRendition)
            .values(**values)
            .on_conflict_do_update(
                constraint=RENDITION_KEY,
                set_={key: values[key] for key in values if key not in RENDITION_IDENTITY},
            )
            .returning(ImageRendition)
        )
    ).scalar_one()
    return stored


async def render_image(capture_id: uuid.UUID, settings: ExtractSettings) -> ImageRendition | None:
    """Read a captured image, re-encode it, keep the result beside it. Never over it."""
    body = await _captured(capture_id)
    if not body:
        return None

    attributes: dict[str, Any] = {"capture.id": str(capture_id)}
    with span("render image", **attributes) as current:
        try:
            rendered = render(body, settings)
        except (OSError, ValueError) as exc:
            # A capture that will not decode is not worth offering again every sweep.
            current.record_exception(exc)
            count("extract.renditions.undecodable")
            logger.warning("image capture %s did not decode: %s", capture_id, exc)
            rendered = None

        stored = await _store(capture_id, rendered, settings)
        current.set_attribute("rendition.bytes", stored.byte_size)
        if rendered is None:
            count("extract.renditions.declined")
        else:
            count("extract.renditions.stored")
            count("extract.renditions.saved_bytes", len(body) - len(rendered.body))
        return stored
