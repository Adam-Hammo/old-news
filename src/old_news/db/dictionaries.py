"""Choosing and training compression dictionaries. Immutable, so loaded ones are cached."""

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

# The trainer refuses outright below this, whatever dictionary size is asked for.
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
    """The newest dictionary for a feed, or None while it has none."""
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
    """The newest dictionary for a host's article pages, a separate scope from a feed's."""
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
        # Unreachable while the foreign key holds, so the row went out of band.
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
    """Feeds with enough documents to learn from and no current dictionary, biggest first."""
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
    """Recent document bodies for a feed, newest first, expanded."""
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
    """Recent page bodies for a host, newest first, expanded."""
    rows = await session.execute(
        select(PageCapture.body)
        .where(PageCapture.host_id == host_id, PageCapture.body != b"")
        .order_by(PageCapture.fetched_at.desc())
        .limit(limit)
    )
    return [await expand(session, body) for (body,) in rows.all()]


def train(samples: list[bytes], settings: StorageSettings) -> Trained | None:
    """Build the best dictionary these bodies support, or None when none beats plain zstd.

    Sizes are measured on a held-out sample, not picked: the trainer degrades when asked
    for more than the scope can use. Outside a transaction — it costs seconds of CPU.
    """
    if len(samples) < max(settings.dictionary_min_samples, MIN_TRAINABLE_SAMPLES):
        return None

    held, training = samples[0], samples[1:]
    level = settings.compression_level
    best: Trained | None = None
    smallest = len(codec.compress(held, level=level))

    for size in settings.dictionary_size_ladder:
        try:
            candidate = zstd.train_dict(training, size)
        except zstd.ZstdError:
            # One unlearnable scope must not fail the sweep for the rest.
            continue

        stored = len(codec.compress(held, level=level, dictionary=candidate))
        if stored >= smallest:
            continue
        smallest = stored
        best = Trained(
            body=candidate.dict_content,
            dict_id=candidate.dict_id,
            sample_count=len(training),
            sample_bytes=sum(len(sample) for sample in training),
        )

    if best is None:
        logger.info("no dictionary size beat plain zstd for %d samples", len(samples))
    return best


async def _store(
    session: AsyncSession, scope: dict[str, uuid.UUID], trained: Trained
) -> ZstdDictionary:
    """Upsert: an identical retrain moves `trained_at` and rewrites no body."""
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
