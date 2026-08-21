"""Carving an item's text out of the document it arrived in, and keeping the bytes."""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import Settings
from old_news.db import (
    DictionaryScope,
    Document,
    Feed,
    FeedCapture,
    Item,
    ItemVersion,
    dictionaries,
)
from old_news.db import bytes as codec
from old_news.ingest import parser
from old_news.observability import count, span

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Stored:
    """A document read back out, ready to parse."""

    feed_id: uuid.UUID
    url: str
    body: bytes


@dataclass(frozen=True, slots=True)
class Carving:
    """One version's text in its stored form, and the dictionary it names."""

    body: bytes
    body_hash: bytes
    dictionary_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Wanted:
    """A head version needing a carving, and whatever the last one left it."""

    identity_key: str
    version_id: uuid.UUID
    held: Carving


def _carved() -> Any:
    """Whether the current parser has already read text out of this version."""
    # Correlated rather than `NOT IN` over the whole table: the stamp matches nearly every
    # row once the sweep has drained, so only the version can narrow it.
    return exists(
        select(FeedCapture.id).where(
            FeedCapture.item_version_id == ItemVersion.id,
            FeedCapture.parser_version == parser.parser_version(),
        )
    )


@db.transactional
async def due_feed_captures(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Documents holding a head version the current parser has not read text out of."""
    rows = await session.execute(
        select(Document.id)
        .join(ItemVersion, ItemVersion.document_id == Document.id)
        .where(ItemVersion.is_head, ~_carved())
        .distinct()
        # uuidv7, so newest first — the same bargain the feed extraction sweep makes.
        .order_by(Document.id.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


@db.transactional
async def _stored(session: AsyncSession, document_id: uuid.UUID) -> Stored | None:
    """The document's bytes, expanded, and the URL its relative links resolve against."""
    row = (
        await session.execute(
            select(Document.feed_id, Document.body, Document.final_url, Feed.url)
            .join(Feed, Feed.id == Document.feed_id)
            .where(Document.id == document_id)
        )
    ).first()
    if row is None:
        return None
    # Where it was served from, not where it was asked for. `Feed.url` is the fallback
    # for documents stored before that was recorded.
    base = row.final_url or row.url
    return Stored(row.feed_id, base, await dictionaries.expand(session, row.body))


@db.transactional
async def _store(
    session: AsyncSession,
    document_id: uuid.UUID,
    stored: Stored,
    parsed: parser.ParsedFeed,
    settings: Settings,
) -> int:
    """One row per head version this document is behind, whether or not it carried text."""
    wanted = await _wanted(session, document_id)
    if not wanted:
        return 0

    # First wins, as `apply_items` does: a repeated identity means the version was made
    # from the earlier entry, so the later one's text belongs to no row.
    texts: dict[str, str] = {}
    for item in parsed.items:
        texts.setdefault(item.identity.key, item.content or item.summary)
    current = await dictionaries.current_for_feed(
        session, stored.feed_id, DictionaryScope.FEED_ITEM
    )
    version = parser.parser_version()

    carried = 0
    for want in wanted:
        text = texts.get(want.identity_key, "")
        carried += bool(text)
        # Nothing found leaves the carving already held standing, and moves only its
        # stamp: an empty row would hide text an earlier parse did find, and the sweep
        # still has to stop offering this document.
        kept = _keep(text, current, settings) if text else want.held
        await session.execute(
            insert(FeedCapture)
            .values(
                item_version_id=want.version_id,
                document_id=document_id,
                body_hash=kept.body_hash,
                body=kept.body,
                dictionary_id=kept.dictionary_id,
                parser_version=version,
            )
            # The stamp moves rather than the bytes: identical text under a new parser
            # is what "already carved" has to mean, or the sweep never drains.
            .on_conflict_do_update(
                index_elements=["item_version_id", "body_hash"],
                set_={"parser_version": version},
            )
        )

    if carried < len(wanted):
        logger.info(
            "document %s carried no text for %d of its versions",
            document_id,
            len(wanted) - carried,
        )
    return len(wanted)


def _keep(text: str, current: dictionaries.Current | None, settings: Settings) -> Carving:
    """The stored form of one item's text, and the dictionary it was compressed against."""
    # Hashed raw, so the constraint answers "is this the same text" rather than "did the
    # same dictionary compress it".
    body = codec.compress(
        text.encode(),
        level=settings.storage.compression_level,
        dictionary=current.dictionary if current else None,
    )
    return Carving(body, hashlib.sha256(text.encode()).digest(), current.id if current else None)


async def _wanted(session: AsyncSession, document_id: uuid.UUID) -> list[Wanted]:
    """Head versions of this document the current parser has not read text out of."""
    rows = (
        await session.execute(
            select(Item.identity_key, ItemVersion.id)
            .join(Item, Item.id == ItemVersion.item_id)
            .where(ItemVersion.document_id == document_id, ItemVersion.is_head, ~_carved())
        )
    ).all()
    if not rows:
        return []

    held = await _held(session, [version_id for _, version_id in rows])
    empty = Carving(b"", hashlib.sha256(b"").digest(), None)
    return [
        Wanted(identity_key, version_id, held.get(version_id, empty))
        for identity_key, version_id in rows
    ]


async def _held(session: AsyncSession, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, Carving]:
    """The carving each of these versions already holds, if any."""
    # `DISTINCT ON`, not the anti-join `ItemVersion.feed_capture` makes: that one reads a
    # row per version and auto-correlates its FROM away when joined against a set.
    rows = await session.execute(
        select(
            FeedCapture.item_version_id,
            FeedCapture.body,
            FeedCapture.body_hash,
            FeedCapture.dictionary_id,
        )
        .ext(distinct_on(FeedCapture.item_version_id))
        .where(FeedCapture.item_version_id.in_(version_ids))
        .order_by(
            FeedCapture.item_version_id, FeedCapture.captured_at.desc(), FeedCapture.id.desc()
        )
    )
    return {
        row.item_version_id: Carving(row.body, row.body_hash, row.dictionary_id)
        for row in rows.all()
    }


async def capture_feed(document_id: uuid.UUID, settings: Settings) -> int:
    """Re-read one stored document and keep what it said about each of its versions."""
    stored = await _stored(document_id)
    if stored is None:
        return 0

    attributes: dict[str, Any] = {"document.id": str(document_id)}
    with span("capture feed text", **attributes) as current:
        parsed = parser.parse(stored.body, url=stored.url)
        current.set_attribute("feed.items", len(parsed.items))

        captured = await _store(document_id, stored, parsed, settings)
        current.set_attribute("feed.captured", captured)
        count("extract.feed_captures.stored", captured)
        return captured
