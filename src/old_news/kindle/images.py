"""The pictures an issue can print, which is what the archive holds plus the bytes."""

import dataclasses
import uuid
from collections.abc import Sequence

from old_news import extract
from old_news.db import ImageRole


@dataclasses.dataclass(frozen=True, slots=True)
class Picture:
    """One held image, and which article asked for it."""

    item_id: uuid.UUID
    url: str
    role: str
    body: bytes


async def pictures(item_ids: Sequence[uuid.UUID]) -> tuple[Picture, ...]:
    """Every usable image behind these articles, with its bytes. One weekly job's worth."""
    found = []
    for held in await extract.held_for(item_ids):
        # A row that lost its bytes between the two reads is one picture, not the issue.
        stored = await extract.bytes_of(held.capture_id)
        if stored is not None:
            found.append(Picture(held.item_id, held.url, held.role, stored[0]))
    return tuple(found)


def leads(found: Sequence[Picture]) -> dict[uuid.UUID, Picture]:
    """The one picture per article that stops a Kindle page having a hole in it."""
    hero: dict[uuid.UUID, Picture] = {}
    for picture in found:
        if picture.role == ImageRole.LEAD:
            hero.setdefault(picture.item_id, picture)
    return hero
