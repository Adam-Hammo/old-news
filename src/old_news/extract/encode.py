"""The Pillow boundary. Re-encoding a held image to the one form we keep of it."""

import io
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import PIL
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import ExtractSettings
from old_news.db import ImageCapture
from old_news.observability import count, span

logger = logging.getLogger(__name__)

# Bumped when anything below changes what comes out, so the archive comes back around.
RULES_REVISION = 1

CONTENT_TYPE = "image/avif"


def encoder_version() -> str:
    return f"{PIL.__version__}+{RULES_REVISION}"


def spec(settings: ExtractSettings) -> str:
    """The recipe, as it is stored: format and the width it was asked to fit."""
    return f"avif-{settings.image_max_width}"


@dataclass(frozen=True, slots=True)
class Encoded:
    """Smaller bytes for the same picture, or nothing when it was already its best form."""

    body: bytes
    content_type: str


@db.transactional
async def due_encodes(
    session: AsyncSession, settings: ExtractSettings, limit: int
) -> list[uuid.UUID]:
    """Images the current encoder has not read. Biggest first, where the bytes are."""
    rows = await session.execute(
        select(ImageCapture.id)
        .where(
            ImageCapture.usable,
            (ImageCapture.spec != spec(settings))
            | (ImageCapture.encoder_version != encoder_version()),
        )
        .order_by(ImageCapture.byte_size.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def _unread(
    session: AsyncSession, capture_id: uuid.UUID, settings: ExtractSettings
) -> bytes | None:
    """The bytes, unless this encoder has already had them."""
    # Checked here as well as in the sweep: with no original to fall back on, a second
    # pass would re-encode its own output and spend a generation for nothing.
    row = (
        await session.execute(
            select(ImageCapture.body, ImageCapture.spec, ImageCapture.encoder_version).where(
                ImageCapture.id == capture_id
            )
        )
    ).first()
    if row is None or (row.spec, row.encoder_version) == (spec(settings), encoder_version()):
        return None
    return row.body


def encode(body: bytes, settings: ExtractSettings) -> Encoded | None:
    """Re-encode one image at reading width. None when what is held already wins."""
    # Outside a transaction: tens of milliseconds of CPU per image.
    with Image.open(io.BytesIO(body)) as opened:
        # Animation would be flattened to its first frame, which is worse than declining.
        if getattr(opened, "n_frames", 1) > 1:
            return None

        width, height = opened.size
        limit = settings.image_max_width
        # AVIF carries alpha, and flattening a transparent logo onto RGB turns its
        # background black. Pillow warns about it, which `filterwarnings` makes fatal.
        transparent = opened.mode in {"RGBA", "LA", "PA"} or "transparency" in opened.info
        source = opened.convert("RGBA" if transparent else "RGB")
        if width > limit:
            source = source.resize((limit, round(height * limit / width)), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        source.save(buffer, "AVIF", quality=settings.image_quality)

    encoded = buffer.getvalue()
    if len(encoded) >= len(body):
        return None
    return Encoded(encoded, CONTENT_TYPE)


@db.transactional
async def _replace(
    session: AsyncSession,
    capture_id: uuid.UUID,
    encoded: Encoded | None,
    settings: ExtractSettings,
) -> None:
    """Stamp the capture read, and swap the bytes when the re-encode won."""
    # The stamp goes on either way, or the sweep offers this image every five minutes for
    # as long as it is held.
    stamp: dict[str, object] = {"spec": spec(settings), "encoder_version": encoder_version()}
    if encoded is not None:
        stamp |= {
            "body": encoded.body,
            "byte_size": len(encoded.body),
            "content_type": encoded.content_type,
        }
    await session.execute(update(ImageCapture).where(ImageCapture.id == capture_id).values(**stamp))


async def encode_image(capture_id: uuid.UUID, settings: ExtractSettings) -> int:
    """Read a held image, re-encode it, keep only the smaller of the two. Bytes saved."""
    body = await _unread(capture_id, settings)
    if not body:
        return 0

    attributes: dict[str, Any] = {"capture.id": str(capture_id)}
    with span("encode image", **attributes) as current:
        try:
            encoded = encode(body, settings)
        except (OSError, ValueError) as exc:
            # An image that will not decode is not worth offering again every sweep.
            current.record_exception(exc)
            count("extract.images.undecodable")
            logger.warning("image capture %s did not decode: %s", capture_id, exc)
            encoded = None

        await _replace(capture_id, encoded, settings)
        saved = len(body) - len(encoded.body) if encoded else 0
        current.set_attribute("image.saved_bytes", saved)
        count("extract.images.reencoded" if encoded else "extract.images.kept_as_served")
        count("extract.images.saved_bytes", saved)
        return saved
