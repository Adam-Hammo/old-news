"""Every write a poll performs. `feeds` is the only table updated; the rest only insert."""

import datetime
import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news.config import StorageSettings
from old_news.db import Document, Feed, Item, ItemVersion, dictionaries
from old_news.db import bytes as codec
from old_news.fetch import Response
from old_news.ingest.normalise import content_fingerprint
from old_news.ingest.parser import ParsedFeed, ParsedItem

logger = logging.getLogger(__name__)

CAPTURED_HEADERS = ("etag", "last-modified", "content-type", "cache-control", "retry-after")


@dataclass(frozen=True, slots=True)
class Applied:
    new_items: int = 0
    new_versions: int = 0
    unchanged: int = 0
    guid_churn: int = 0
    duplicate_identity: int = 0


def identity_of(item: ParsedItem) -> tuple[str, str]:
    """The key an article is recognised by, and which tier produced it."""
    if item.guid:
        return item.guid, "guid"
    if item.canonical_url:
        return item.canonical_url, "link"

    digest = hashlib.sha256()
    for part in (
        item.title,
        item.published_at.isoformat() if item.published_at else "",
        item.summary,
    ):
        digest.update(part.encode())
        digest.update(b"\x1f")
    return digest.hexdigest(), "hash"


def fingerprint_of(item: ParsedItem) -> bytes:
    return content_fingerprint(
        item.title,
        item.author,
        item.canonical_url,
        item.summary,
        item.content,
        item.comments_url,
        "\x1e".join(item.tags),
        "\x1e".join(sorted(str(sorted(e.items())) for e in item.enclosures)),
        item.published_at.isoformat() if item.published_at else "",
        item.updated_at.isoformat() if item.updated_at else "",
    )


async def previous_document_hash(session: AsyncSession, feed_id: uuid.UUID) -> bytes | None:
    """The last body stored for this feed, so a reverted redaction still reads as a change."""
    return (
        await session.execute(
            select(Document.body_hash)
            .where(Document.feed_id == feed_id)
            .order_by(Document.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def record_document(
    session: AsyncSession,
    feed: Feed,
    response: Response,
    parsed: ParsedFeed,
    storage: StorageSettings,
) -> Document | None:
    """Store the body if it differs from the previous one. Written before parsing."""
    # Hashed raw: the hash answers "did this feed change", not "what did we store".
    body_hash = hashlib.sha256(response.body).digest()
    if body_hash == await previous_document_hash(session, feed.id):
        return None

    current = await dictionaries.current_for_feed(session, feed.id)
    document = Document(
        feed_id=feed.id,
        status=response.status,
        body_hash=body_hash,
        body=codec.compress(
            response.body,
            level=storage.compression_level,
            dictionary=current.dictionary if current else None,
        ),
        dictionary_id=current.id if current else None,
        headers={name: value for name in CAPTURED_HEADERS if (value := response.header(name))},
        parse_ok=parsed.ok,
        parse_note=parsed.note,
    )
    session.add(document)
    await session.flush()
    return document


@dataclass(frozen=True, slots=True)
class Current:
    """What a poll needs to know about an item it has seen before."""

    item_id: uuid.UUID
    version_id: uuid.UUID
    content_hash: bytes
    canonical_url: str


async def current_versions(session: AsyncSession, feed_id: uuid.UUID) -> dict[str, Current]:
    """Every item in this feed with the tail of its chain, keyed by identity.

    Columns, not entities: selecting `ItemVersion` would load every body to compare
    hashes. The anti-join is what "tail of the chain" means — nothing supersedes it.
    """
    rows = await session.execute(
        select(
            Item.identity_key,
            Item.id,
            ItemVersion.id,
            ItemVersion.content_hash,
            ItemVersion.canonical_url,
        )
        .join(ItemVersion, ItemVersion.item_id == Item.id)
        .where(Item.feed_id == feed_id)
        .where(ItemVersion.is_head)
    )
    return {
        identity_key: Current(item_id, version_id, content_hash, canonical_url)
        for identity_key, item_id, version_id, content_hash, canonical_url in rows
    }


async def apply_items(
    session: AsyncSession,
    feed: Feed,
    document: Document,
    parsed_items: tuple[ParsedItem, ...],
    *,
    observed_at: datetime.datetime,
) -> Applied:
    existing = await current_versions(session, feed.id)
    known_urls = {current.canonical_url for current in existing.values() if current.canonical_url}

    new_items = new_versions = unchanged = churn = duplicates = 0
    seen: set[str] = set()

    for parsed in parsed_items:
        key, source = identity_of(parsed)

        # The same identity twice in one document, so the first wins: a second insert
        # breaks the identity constraint and a second version invents an edit.
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)

        fingerprint = fingerprint_of(parsed)
        found = existing.get(key)

        if found is None:
            # A new key on a URL we hold means the publisher changed its guid scheme.
            # Recorded, never merged: some feeds reuse a URL for live-updating pages.
            if parsed.canonical_url and parsed.canonical_url in known_urls:
                churn += 1
                logger.warning(
                    "guid churn on feed %s: new key %r for known url %s",
                    feed.id,
                    key[:120],
                    parsed.canonical_url,
                )

            item = Item(feed_id=feed.id, guid=parsed.guid, identity_key=key, identity_source=source)
            session.add(item)
            await session.flush()
            session.add(_version(parsed, item.id, document.id, fingerprint, observed_at, None))
            new_items += 1
            continue

        if found.content_hash == fingerprint:
            unchanged += 1
            continue

        session.add(
            _version(parsed, found.item_id, document.id, fingerprint, observed_at, found.version_id)
        )
        new_versions += 1

    if duplicates:
        logger.warning("feed %s repeated %d identities in one document", feed.id, duplicates)

    await session.flush()
    return Applied(new_items, new_versions, unchanged, churn, duplicates)


def _version(
    parsed: ParsedItem,
    item_id: uuid.UUID,
    document_id: uuid.UUID,
    fingerprint: bytes,
    observed_at: datetime.datetime,
    supersedes_id: uuid.UUID | None,
) -> ItemVersion:
    published = parsed.published_at
    # A publisher's clock in the future poisons every sort built on it later.
    if published and published > observed_at:
        published = observed_at

    return ItemVersion(
        item_id=item_id,
        document_id=document_id,
        supersedes_id=supersedes_id,
        observed_at=observed_at,
        title=parsed.title,
        author=parsed.author,
        url=parsed.url,
        canonical_url=parsed.canonical_url,
        summary=parsed.summary,
        content=parsed.content,
        tags=list(parsed.tags),
        enclosures=list(parsed.enclosures),
        comments_url=parsed.comments_url,
        published_at=published,
        updated_at=parsed.updated_at,
        content_hash=fingerprint,
    )
