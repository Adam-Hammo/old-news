"""Choosing and training compression dictionaries.

A dictionary is immutable once written, so loaded ones are cached for the life of the
process and a read almost never touches Postgres.
"""

import datetime
import logging
import uuid
from compression import zstd
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news.config import StorageSettings
from old_news.db import bytes as codec
from old_news.db.models import Document, PageCapture, ZstdDictionary
from old_news.db.session import transactional

logger = logging.getLogger(__name__)

# zstd's trainer splits the samples it is given and refuses outright below a handful,
# whatever dictionary size is asked for. Configuring fewer than this cannot work, so
# it is a floor rather than a default.
MIN_TRAINABLE_SAMPLES = 8

_loaded: dict[int, zstd.ZstdDict] = {}


@dataclass(frozen=True, slots=True)
class Trained:
    """A dictionary and what it was built from, before it has a row."""

    body: bytes
    dict_id: int
    sample_count: int
    sample_bytes: int


@dataclass(frozen=True, slots=True)
class Current:
    """The dictionary to compress with, and the row a body should point at."""

    id: uuid.UUID
    dictionary: zstd.ZstdDict


async def current_for_feed(session: AsyncSession, feed_id: uuid.UUID) -> Current | None:
    """The newest dictionary for a feed, or None while it has none.

    None is not a failure — it is what every scope starts as, and plain zstd is always
    readable.
    """
    row = (
        await session.execute(
            select(ZstdDictionary.id, ZstdDictionary.dict_id, ZstdDictionary.body)
            .where(ZstdDictionary.feed_id == feed_id)
            .order_by(ZstdDictionary.trained_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return Current(row.id, _cached(row.dict_id, row.body))


async def current_for_host(session: AsyncSession, host_id: uuid.UUID) -> Current | None:
    """The newest dictionary for a host's article pages.

    A separate scope from a feed's, because two pages from one publisher share a template
    where two documents from one feed share almost everything.
    """
    row = (
        await session.execute(
            select(ZstdDictionary.id, ZstdDictionary.dict_id, ZstdDictionary.body)
            .where(ZstdDictionary.host_id == host_id)
            .order_by(ZstdDictionary.trained_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return Current(row.id, _cached(row.dict_id, row.body))


async def expand(session: AsyncSession, body: bytes) -> bytes:
    """Read a stored body back, fetching whatever dictionary it names."""
    dict_id = codec.dictionary_id(body)
    if dict_id == codec.NO_DICTIONARY:
        return codec.decompress(body)
    return codec.decompress(body, await _load(session, dict_id))


async def _load(session: AsyncSession, dict_id: int) -> zstd.ZstdDict:
    if dict_id in _loaded:
        return _loaded[dict_id]
    stored = (
        await session.execute(select(ZstdDictionary.body).where(ZstdDictionary.dict_id == dict_id))
    ).scalar_one_or_none()
    if stored is None:
        # The foreign key makes this unreachable from a consistent database, so it
        # means the row was removed out of band and those bodies are now unreadable.
        raise LookupError(f"no stored zstd dictionary {dict_id}")
    return _cached(dict_id, stored)


def _cached(dict_id: int, body: bytes) -> zstd.ZstdDict:
    if dict_id not in _loaded:
        _loaded[dict_id] = zstd.ZstdDict(body)
    return _loaded[dict_id]


@transactional
async def feeds_wanting_a_dictionary(
    session: AsyncSession, settings: StorageSettings, limit: int
) -> list[uuid.UUID]:
    """Feeds with enough documents to learn from and no current dictionary.

    Ordered by document count so the feeds paying the most for compression get one
    first — which is also where the training set is best.
    """
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=settings.dictionary_max_age_seconds
    )
    fresh = (
        select(ZstdDictionary.feed_id)
        .where(ZstdDictionary.feed_id.is_not(None), ZstdDictionary.trained_at > cutoff)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Document.feed_id)
        .where(Document.feed_id.not_in(fresh))
        .group_by(Document.feed_id)
        .having(func.count(Document.id) >= settings.dictionary_min_samples)
        .order_by(func.count(Document.id).desc())
        .limit(limit)
    )
    return [feed_id for (feed_id,) in rows.all()]


@transactional
async def feed_samples(session: AsyncSession, feed_id: uuid.UUID, limit: int) -> list[bytes]:
    """Recent document bodies for a feed, expanded.

    Newest first: a dictionary should describe what the publisher serves now, not what
    it served when the feed was first subscribed to. Expanded here rather than by the
    caller because a sample compressed against an earlier dictionary needs a lookup to
    read, and this is where the session is.
    """
    rows = await session.execute(
        select(Document.body)
        .where(Document.feed_id == feed_id)
        .order_by(Document.fetched_at.desc())
        .limit(limit)
    )
    return [await expand(session, body) for (body,) in rows.all()]


@transactional
async def hosts_wanting_a_dictionary(
    session: AsyncSession, settings: StorageSettings, limit: int
) -> list[uuid.UUID]:
    """Hosts with enough captured pages to learn from and no current dictionary."""
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=settings.dictionary_max_age_seconds
    )
    fresh = (
        select(ZstdDictionary.host_id)
        .where(ZstdDictionary.host_id.is_not(None), ZstdDictionary.trained_at > cutoff)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(PageCapture.host_id)
        .where(PageCapture.host_id.not_in(fresh), PageCapture.body != b"")
        .group_by(PageCapture.host_id)
        .having(func.count(PageCapture.id) >= settings.dictionary_min_samples)
        .order_by(func.count(PageCapture.id).desc())
        .limit(limit)
    )
    return [host_id for (host_id,) in rows.all()]


@transactional
async def host_samples(session: AsyncSession, host_id: uuid.UUID, limit: int) -> list[bytes]:
    """Recent page bodies for a host, expanded. Newest first, like a feed's."""
    rows = await session.execute(
        select(PageCapture.body)
        .where(PageCapture.host_id == host_id, PageCapture.body != b"")
        .order_by(PageCapture.fetched_at.desc())
        .limit(limit)
    )
    return [await expand(session, body) for (body,) in rows.all()]


def train(samples: list[bytes], settings: StorageSettings) -> Trained | None:
    """Build a dictionary from expanded bodies. None when there is too little to learn."""
    if len(samples) < max(settings.dictionary_min_samples, MIN_TRAINABLE_SAMPLES):
        return None

    try:
        body = zstd.train_dict(samples, settings.dictionary_max_bytes)
    except zstd.ZstdError:
        # A publisher whose bodies the trainer cannot make sense of must not fail the
        # nightly sweep for every other feed. Plain zstd remains correct.
        logger.warning("could not train a dictionary from %d samples", len(samples))
        return None

    return Trained(
        body=body.dict_content,
        dict_id=body.dict_id,
        sample_count=len(samples),
        sample_bytes=sum(len(sample) for sample in samples),
    )


async def _store(
    session: AsyncSession, scope: dict[str, uuid.UUID], trained: Trained
) -> ZstdDictionary:
    """A retrain that produces an identical dictionary only moves `trained_at`, which
    says the scope was looked at and had nothing new to learn. No body is ever rewritten
    and no existing dictionary is replaced."""
    values = {
        "dict_id": trained.dict_id,
        "body": trained.body,
        "sample_count": trained.sample_count,
        "sample_bytes": trained.sample_bytes,
        **scope,
    }
    stored = (
        await session.execute(
            insert(ZstdDictionary)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["dict_id", "feed_id", "host_id"],
                set_={"trained_at": func.now(), "sample_count": trained.sample_count},
            )
            .returning(ZstdDictionary)
        )
    ).scalar_one()
    logger.info(
        "dictionary %s for %s trained from %d bodies",
        trained.dict_id,
        scope,
        trained.sample_count,
    )
    return stored


@transactional
async def store_for_feed(
    session: AsyncSession, feed_id: uuid.UUID, trained: Trained
) -> ZstdDictionary:
    """Record a dictionary against a feed's documents."""
    return await _store(session, {"feed_id": feed_id}, trained)


@transactional
async def store_for_host(
    session: AsyncSession, host_id: uuid.UUID, trained: Trained
) -> ZstdDictionary:
    """Record a dictionary against a publisher's article pages."""
    return await _store(session, {"host_id": host_id}, trained)
