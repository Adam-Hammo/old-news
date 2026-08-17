"""Every write a poll performs.

`feeds` is the only table updated here. Items, versions and documents are only
ever inserted, which is what makes read state safe by construction rather than
by care.
"""

import datetime
import hashlib
import logging
import uuid
from compression import zstd
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from old_news.db import Document, Feed, Item, ItemVersion
from old_news.fetch import Response
from old_news.ingest.normalise import content_fingerprint
from old_news.ingest.parser import ParsedFeed, ParsedItem

logger = logging.getLogger(__name__)

CAPTURED_HEADERS = ("etag", "last-modified", "content-type", "cache-control", "retry-after")

# Postgres TOASTs these with pglz, which manages about 2x on feed XML. zstd gets
# 5-6x, and documents are the great majority of the database.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def decompress(body: bytes) -> bytes:
    """The way back. Bodies stored before compression began start with `<` or a BOM,
    never with the zstd magic, so both read the same way and nothing needs migrating."""
    return zstd.decompress(body) if body.startswith(ZSTD_MAGIC) else body


@dataclass(frozen=True, slots=True)
class Applied:
    new_items: int = 0
    new_versions: int = 0
    unchanged: int = 0
    guid_churn: int = 0


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
    """The last body stored for this feed, not any body ever stored.

    Comparing against the previous one rather than every one keeps a publisher
    reverting a redaction visible as A -> B -> A.
    """
    return (
        await session.execute(
            select(Document.body_hash)
            .where(Document.feed_id == feed_id)
            .order_by(Document.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def record_document(
    session: AsyncSession, feed: Feed, response: Response, parsed: ParsedFeed
) -> Document | None:
    """Store the body if it differs from the previous one. Written before parsing."""
    # Hashed raw: the hash answers "did this feed change", not "what did we store".
    body_hash = hashlib.sha256(response.body).digest()
    if body_hash == await previous_document_hash(session, feed.id):
        return None

    document = Document(
        feed_id=feed.id,
        status=response.status,
        body_hash=body_hash,
        body=zstd.compress(response.body),
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

    Four columns, not whole entities: a poll only compares hashes, and selecting
    `ItemVersion` would drag every article body in the feed into memory to do it.

    One query, not one per item. The anti-join is what "the tail of the chain"
    means — the version nothing supersedes.
    """
    successor = aliased(ItemVersion)
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
        .where(~select(successor.id).where(successor.supersedes_id == ItemVersion.id).exists())
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

    new_items = new_versions = unchanged = churn = 0

    for parsed in parsed_items:
        key, source = identity_of(parsed)
        fingerprint = fingerprint_of(parsed)
        found = existing.get(key)

        if found is None:
            # An unseen key on a URL we already hold means the publisher changed
            # its guid scheme — a platform move, usually. Recorded, never merged:
            # some feeds legitimately reuse a URL for live-updating pages.
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

    await session.flush()
    return Applied(new_items, new_versions, unchanged, churn)


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
