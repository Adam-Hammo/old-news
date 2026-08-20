"""Choosing and training compression dictionaries. Immutable, so loaded ones are cached."""

import datetime
import logging
import uuid
from compression import zstd
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news.config import StorageSettings
from old_news.db import bytes as codec
from old_news.db.models import (
    DictionaryScope,
    Document,
    FeedCapture,
    PageCapture,
    ZstdDictionary,
)
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


@dataclass(frozen=True, slots=True)
class _Source:
    """Where one scope's bytes live, and the column a dictionary for them is keyed by."""

    key: Any
    body: Any
    at: Any
    frm: Any
    scoped_by: Any


# Every scope is the same three questions — who has enough to learn from, what did they
# send, where does the row point — so they differ only in this table. Item text is
# reached through its document, which is what says which feed served it.
_SOURCES: dict[DictionaryScope, _Source] = {
    DictionaryScope.FEED_DOCUMENT: _Source(
        key=Document.feed_id,
        body=Document.body,
        at=Document.fetched_at,
        frm=Document,
        scoped_by=ZstdDictionary.feed_id,
    ),
    DictionaryScope.FEED_ITEM: _Source(
        key=Document.feed_id,
        body=FeedCapture.body,
        at=FeedCapture.captured_at,
        frm=FeedCapture.__table__.join(Document, Document.id == FeedCapture.document_id),
        scoped_by=ZstdDictionary.feed_id,
    ),
    DictionaryScope.HOST_PAGE: _Source(
        key=PageCapture.host_id,
        body=PageCapture.body,
        at=PageCapture.fetched_at,
        frm=PageCapture,
        scoped_by=ZstdDictionary.host_id,
    ),
}


def _scoped(scope: DictionaryScope, key_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Which of the two nullable keys a scope hangs off."""
    return {_SOURCES[scope].scoped_by.key: key_id}


async def _current(
    session: AsyncSession, scope: DictionaryScope, key_id: uuid.UUID
) -> Current | None:
    row = (
        await session.execute(
            select(ZstdDictionary.id, ZstdDictionary.dict_id, ZstdDictionary.body)
            .filter_by(scope=scope, **_scoped(scope, key_id))
            .order_by(ZstdDictionary.trained_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return Current(row.id, _cached(row.dict_id, row.body))


async def current_for_feed(
    session: AsyncSession, feed_id: uuid.UUID, scope: DictionaryScope
) -> Current | None:
    """The newest dictionary for a feed's documents or its item text, or None while it has none."""
    return await _current(session, scope, feed_id)


async def current_for_host(session: AsyncSession, host_id: uuid.UUID) -> Current | None:
    """The newest dictionary for a host's article pages, a separate scope from a feed's."""
    return await _current(session, DictionaryScope.HOST_PAGE, host_id)


async def expand(session: AsyncSession, body: bytes) -> bytes:
    """Read a stored body back, fetching whatever dictionary it names."""
    dict_id = codec.dictionary_id(body)
    if dict_id == codec.NO_DICTIONARY:
        return codec.decompress(body)
    return codec.decompress(body, await _load(session, dict_id))


async def _load(session: AsyncSession, dict_id: int) -> zstd.ZstdDict:
    if dict_id in _loaded:
        return _loaded[dict_id]
    # One row, not the only row: `dict_id` hashes the dictionary's own bytes, so two
    # scopes that trained to the same bytes hold the same dictionary. Asking for exactly
    # one made every read of an affected body raise instead.
    stored = (
        await session.execute(
            select(ZstdDictionary.body).where(ZstdDictionary.dict_id == dict_id).limit(1)
        )
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
async def wanting_a_dictionary(
    session: AsyncSession, settings: StorageSettings, scope: DictionaryScope, limit: int
) -> list[uuid.UUID]:
    """Keys with enough bodies of this kind to learn from and no current dictionary."""
    source = _SOURCES[scope]
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=settings.dictionary_max_age_seconds
    )
    fresh = (
        select(source.scoped_by)
        .where(ZstdDictionary.scope == scope, ZstdDictionary.trained_at > cutoff)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(source.key)
        .select_from(source.frm)
        .where(source.key.not_in(fresh), source.body != b"")
        .group_by(source.key)
        .having(func.count() >= settings.dictionary_min_samples)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [key_id for (key_id,) in rows.all()]


@transactional
async def samples(
    session: AsyncSession, scope: DictionaryScope, key_id: uuid.UUID, limit: int
) -> list[bytes]:
    """Recent bodies of this kind for one key, newest first, expanded."""
    source = _SOURCES[scope]
    rows = await session.execute(
        select(source.body)
        .select_from(source.frm)
        .where(source.key == key_id, source.body != b"")
        .order_by(source.at.desc())
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


@transactional
async def store(
    session: AsyncSession, scope: DictionaryScope, key_id: uuid.UUID, trained: Trained
) -> ZstdDictionary:
    """Record a dictionary against what produced its bytes."""
    # Upsert: an identical retrain moves `trained_at` and rewrites no body.
    values = {
        "dict_id": trained.dict_id,
        "scope": scope,
        "body": trained.body,
        "sample_count": trained.sample_count,
        "sample_bytes": trained.sample_bytes,
        **_scoped(scope, key_id),
    }
    stored = (
        await session.execute(
            insert(ZstdDictionary)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["dict_id", "scope", "feed_id", "host_id"],
                set_={"trained_at": func.now(), "sample_count": trained.sample_count},
            )
            .returning(ZstdDictionary)
        )
    ).scalar_one()
    logger.info(
        "%s dictionary %s for %s trained from %d bodies",
        scope,
        trained.dict_id,
        key_id,
        trained.sample_count,
    )
    return stored
