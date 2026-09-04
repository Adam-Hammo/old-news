"""The working directory a converter reads: one file per article, its pictures, a manifest."""

import dataclasses
import datetime
import hashlib
import json
import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from old_news.config import KindleSettings
from old_news.extract import encode
from old_news.kindle import plate, render
from old_news.kindle.images import Picture, leads
from old_news.kindle.selection import Candidate

logger = logging.getLogger(__name__)

DATELINE = "%-d %B %Y"

ARTICLES, IMAGES = "articles", "images"


@dataclasses.dataclass(frozen=True, slots=True)
class Placed:
    """Where one article ended up, which is what the ledger records."""

    item_id: uuid.UUID
    section: str
    position: int


@dataclasses.dataclass(frozen=True, slots=True)
class Layout:
    """A directory the converter can read, and what to call what comes out of it."""

    manifest: Path
    title: str
    subject: str
    placed: tuple[Placed, ...]


def _dateline(at: datetime.datetime | None) -> str:
    return at.strftime(DATELINE) if at else ""


def _tally(count: int, chars: int) -> str:
    return f"{count} articles · {render.minutes(chars)} min"


def _write_pictures(
    work: Path, found: Sequence[Picture], settings: KindleSettings
) -> dict[tuple[uuid.UUID, str], str]:
    """Every picture flattened to JPEG once, named after its bytes so furniture is one file."""
    (work / IMAGES).mkdir(parents=True, exist_ok=True)

    written: dict[tuple[uuid.UUID, str], str] = {}
    for picture in found:
        digest = hashlib.sha256(picture.body).hexdigest()[:16]
        # The href a page uses, which sits a directory below where the file is written.
        relative = f"../{IMAGES}/{digest}.jpg"
        target = work / IMAGES / f"{digest}.jpg"
        if not target.exists():
            try:
                flattened = encode.flatten(
                    picture.body,
                    max_width=settings.image_max_width,
                    quality=settings.image_quality,
                )
            except (OSError, ValueError) as exc:
                logger.warning("image for %s did not decode: %s", picture.url, exc)
                continue
            target.write_bytes(flattened.body)
        written[picture.item_id, picture.url] = relative
    return written


def lay_out(
    work: Path,
    candidates: Sequence[Candidate],
    found: Sequence[Picture],
    settings: KindleSettings,
    at: datetime.datetime,
) -> Layout:
    """Set every article as a page, and describe the issue for the recipe to read."""
    pictures = _write_pictures(work, found, settings)
    hero = leads(found)
    (work / ARTICLES).mkdir(parents=True, exist_ok=True)

    sections: list[dict] = []
    placed: list[Placed] = []
    chars = 0

    for position, candidate in enumerate(candidates, start=1):
        item = candidate.item_id
        lead = hero.get(item)
        body = render.to_html(
            render.without_title(candidate.body, candidate.title),
            {url: name for (owner, url), name in pictures.items() if owner == item},
        )
        relative = f"{ARTICLES}/{position:04d}.html"
        (work / relative).write_text(
            render.page(
                title=candidate.title,
                outlet=candidate.outlet,
                author=candidate.author,
                dateline=_dateline(candidate.published_at),
                url=candidate.url,
                lead=pictures.get((item, lead.url), "") if lead else "",
                body=body,
            ),
            encoding="utf-8",
        )

        if not sections or sections[-1]["title"] != candidate.outlet:
            sections.append({"title": candidate.outlet, "articles": []})
        sections[-1]["articles"].append(
            {
                "file": str((work / relative).resolve()),
                "title": candidate.title,
                "author": candidate.author,
                "description": render.teaser(candidate.body),
                "date": _dateline(candidate.published_at),
            }
        )
        placed.append(Placed(item, candidate.outlet, position))
        chars += len(candidate.body)

    dateline, tally = _dateline(at), _tally(len(candidates), chars)
    title = f"{settings.title} — {dateline}"
    subject = f"{dateline} · {tally}"

    (work / "cover.svg").write_text(
        plate.cover(settings.title, [dateline, tally]), encoding="utf-8"
    )

    manifest = work / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "title": title,
                "date": at.date().isoformat(),
                "subject": subject,
                "cover": str((work / "cover.svg").resolve()),
                "sections": sections,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return Layout(manifest, title, subject, tuple(placed))
