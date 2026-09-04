"""The calibre boundary. It is handed a manifest and asked for a periodical, nothing else."""

import asyncio
import logging
import os
from pathlib import Path

from old_news.config import KindleSettings

logger = logging.getLogger(__name__)

RECIPE = Path(__file__).parent / "issue.recipe"

# Calibre is a Qt application even when it is only converting.
HEADLESS = {"QT_QPA_PLATFORM": "offscreen"}


class ConversionFailed(RuntimeError):
    """The converter refused the book. Its own words are the only diagnosis there is."""


def _read(out: Path) -> bytes:
    return out.read_bytes() if out.exists() else b""


async def to_epub(manifest: Path, out: Path, settings: KindleSettings) -> bytes:
    """Run the recipe over an already-written manifest and hand back the book."""
    process = await asyncio.create_subprocess_exec(
        settings.converter,
        str(RECIPE),
        str(out),
        "--output-profile=kindle_pw3",
        env=os.environ | HEADLESS | {"OLD_NEWS_MANIFEST": str(manifest)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        async with asyncio.timeout(settings.convert_timeout_seconds):
            logged, _ = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ConversionFailed(f"{settings.converter} did not finish") from None

    output = logged.decode(errors="replace")
    if process.returncode != 0:
        raise ConversionFailed(output.strip()[-2000:] or f"exit {process.returncode}")

    logger.debug("%s: %s", settings.converter, output[-2000:])
    body = await asyncio.to_thread(_read, out)
    if not body:
        raise ConversionFailed("the converter wrote no book")
    return body
