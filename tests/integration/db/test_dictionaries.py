"""A body must stay readable across a retrain, and a dictionary in use must stay put."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import StorageSettings
from old_news.db import Document, ZstdDictionary, dictionaries
from old_news.db import bytes as codec
from old_news.politeness import ensure
from old_news.subscriptions.service import add

SETTINGS = StorageSettings(dictionary_min_samples=10, dictionary_sample_limit=30)


def _documents(count: int, *, era: str = "first") -> list[bytes]:
    """`era` changes what the publisher's markup looks like, so a retrain has something
    new to learn rather than reproducing the dictionary it already has."""
    return [
        f'<?xml version="1.0"?><rss><channel><title>Loopback {era}</title>'
        f"<item><guid>{era}-{n}</guid><description>{era} story {n}</description></item>"
        "</channel></rss>".encode()
        * 40
        for n in range(count)
    ]


@db.transactional
async def _store_documents(session: AsyncSession, feed_id: uuid.UUID, bodies: list[bytes]) -> None:
    """Written the way a poll writes them, so whatever dictionary exists gets used."""
    for body in bodies:
        current = await dictionaries.current_for_feed(session, feed_id)
        session.add(
            Document(
                feed_id=feed_id,
                status=200,
                body_hash=body[:32],
                body=codec.compress(
                    body,
                    level=SETTINGS.compression_level,
                    dictionary=current.dictionary if current else None,
                ),
                dictionary_id=current.id if current else None,
            )
        )
    await session.flush()


@db.transactional
async def _read_back(session: AsyncSession, feed_id: uuid.UUID) -> list[bytes]:
    rows = await session.execute(select(Document.body).where(Document.feed_id == feed_id))
    return [await dictionaries.expand(session, body) for (body,) in rows.all()]


async def _train(feed_id: uuid.UUID) -> ZstdDictionary:
    samples = await dictionaries.feed_samples(feed_id, SETTINGS.dictionary_sample_limit)
    trained = dictionaries.train(samples, SETTINGS)
    assert trained is not None
    return await dictionaries.store_for_feed(feed_id, trained)


async def _feed() -> uuid.UUID:
    feed = await add("https://loopback.example.com/feed.xml")
    assert feed is not None
    return feed.id


async def test_bodies_stored_before_a_dictionary_still_read_after_one_exists(clean: None):
    """No migration rewrites anything, so the old bodies have to keep working."""
    feed_id = await _feed()
    before = _documents(10)
    await _store_documents(feed_id, before)

    await _train(feed_id)
    after = _documents(3)
    await _store_documents(feed_id, after)

    assert await _read_back(feed_id) == before + after


async def test_a_body_reads_back_across_a_retrain(clean: None):
    """Two dictionaries for one feed, and each body finds its own."""
    feed_id = await _feed()
    await _store_documents(feed_id, _documents(10))
    first = await _train(feed_id)

    early = _documents(2, era="second")
    await _store_documents(feed_id, early)

    # A publisher that changed its markup, so there is genuinely something new to learn.
    await _store_documents(feed_id, _documents(10, era="second"))
    second = await _train(feed_id)
    assert second.dict_id != first.dict_id

    late = _documents(2, era="third")
    await _store_documents(feed_id, late)

    stored = await _read_back(feed_id)
    assert early[0] in stored
    assert late[0] in stored


async def test_retraining_on_unchanged_data_is_a_no_op(clean: None):
    """`dict_id` hashes the content, so an unchanged feed retrains to the same
    dictionary. That has to be nothing happening, not a failed nightly job."""
    feed_id = await _feed()
    await _store_documents(feed_id, _documents(10))

    first = await _train(feed_id)
    second = await _train(feed_id)

    assert second.id == first.id
    assert second.dict_id == first.dict_id
    assert second.trained_at > first.trained_at


async def test_a_feed_with_a_dictionary_is_not_offered_another(clean: None):
    feed_id = await _feed()
    await _store_documents(feed_id, _documents(10))

    assert await dictionaries.feeds_wanting_a_dictionary(SETTINGS, 5) == [feed_id]
    await _train(feed_id)
    assert await dictionaries.feeds_wanting_a_dictionary(SETTINGS, 5) == []


async def test_a_dictionary_in_use_cannot_be_dropped(clean: None):
    """What makes the archive safe: the bytes and their dictionary share a dump."""
    feed_id = await _feed()
    await _store_documents(feed_id, _documents(10))
    stored = await _train(feed_id)
    await _store_documents(feed_id, _documents(1))

    with pytest.raises(IntegrityError):
        async with db.session() as session:
            await session.execute(
                text("DELETE FROM zstd_dictionaries WHERE id = :id"), {"id": stored.id}
            )


async def test_a_dictionary_needs_exactly_one_scope(clean: None):
    """The check constraint, not a convention."""
    async with db.session() as session:
        host_id = await ensure(session, "loopback.example.com")

    for scopes in ({}, {"feed_id": uuid.uuid4(), "host_id": host_id}):
        with pytest.raises(IntegrityError):
            async with db.session() as session:
                session.add(
                    ZstdDictionary(dict_id=1, body=b"x", sample_count=1, sample_bytes=1, **scopes)
                )
                await session.flush()
