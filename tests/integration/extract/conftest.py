"""Building items and versions by hand, since a poll is not what is under test here."""

import datetime
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import (
    CaptureOutcome,
    Document,
    ExtractionImage,
    Item,
    ItemVersion,
    PageCapture,
    PageExtraction,
)
from old_news.db import bytes as codec
from old_news.politeness import ensure
from old_news.subscriptions.service import add


@db.transactional
async def _document(session: AsyncSession, feed_id: uuid.UUID) -> uuid.UUID:
    document = Document(feed_id=feed_id, status=200, body_hash=b"0" * 32, body=b"<rss/>")
    session.add(document)
    await session.flush()
    return document.id


@db.transactional
async def _version(
    session: AsyncSession,
    item_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    title: str,
    url: str,
    observed_at: datetime.datetime,
    supersedes_id: uuid.UUID | None,
) -> uuid.UUID:
    version = ItemVersion(
        item_id=item_id,
        document_id=document_id,
        supersedes_id=supersedes_id,
        title=title,
        url=url,
        canonical_url=url,
        observed_at=observed_at,
        content_hash=uuid.uuid4().bytes,
    )
    session.add(version)
    await session.flush()
    return version.id


@db.transactional
async def _item(session: AsyncSession, feed_id: uuid.UUID) -> uuid.UUID:
    key = str(uuid.uuid4())
    item = Item(feed_id=feed_id, guid=key, identity_key=key, identity_source="guid")
    session.add(item)
    await session.flush()
    return item.id


@pytest.fixture
def article() -> Callable[..., Coroutine[Any, Any, list[uuid.UUID]]]:
    """An item with one version per title given, chained newest last.

    `aged` backdates every version so the settle window has elapsed; the default leaves
    them just-observed, which is what an unsettled head looks like.
    """

    async def build(
        feed_id: uuid.UUID, *titles_and_urls: tuple[str, str], aged: bool = True
    ) -> list[uuid.UUID]:
        document_id = await _document(feed_id)
        item_id = await _item(feed_id)
        now = datetime.datetime.now(datetime.UTC)
        offset = datetime.timedelta(days=1) if aged else datetime.timedelta(0)

        ids: list[uuid.UUID] = []
        for index, (title, url) in enumerate(titles_and_urls):
            ids.append(
                await _version(
                    item_id,
                    document_id,
                    title=title,
                    url=url,
                    observed_at=now - offset + datetime.timedelta(seconds=index),
                    supersedes_id=ids[-1] if ids else None,
                )
            )
        return ids

    return build


@pytest.fixture
async def feed_id() -> uuid.UUID:
    feed = await add("https://loopback.example.com/feed.xml")
    assert feed is not None
    return feed.id


@db.transactional
async def _extraction(
    session: AsyncSession, version_id: uuid.UUID, host: str, slots: tuple[tuple[str, str], ...]
) -> list[uuid.UUID]:
    capture = PageCapture(
        item_version_id=version_id,
        host_id=await ensure(session, host),
        url=f"https://{host}/article",
        status=200,
        outcome=CaptureOutcome.OK,
        body_hash=b"0" * 32,
        body=b"stored",
    )
    session.add(capture)
    await session.flush()

    extraction = PageExtraction(
        item_version_id=version_id,
        page_capture_id=capture.id,
        extractor="test",
        extractor_version="0",
        body="Words.",
    )
    session.add(extraction)
    await session.flush()

    made: list[uuid.UUID] = []
    for position, (url, role) in enumerate(slots):
        image = ExtractionImage(extraction_id=extraction.id, url=url, role=role, position=position)
        session.add(image)
        await session.flush()
        made.append(image.id)
    return made


@pytest.fixture
def image_slots(feed_id, article) -> Callable[..., Coroutine[Any, Any, list[uuid.UUID]]]:
    """An extraction with the given image slots, built without running the extractor."""

    async def build(*slots: tuple[str, str], host: str = "loopback.example.com") -> list[uuid.UUID]:
        version_id = (await article(feed_id, ("An article", f"https://{host}/article")))[0]
        return await _extraction(version_id, host, slots)

    return build


@db.transactional
async def _store_capture(
    session: AsyncSession, version_id: uuid.UUID, body: bytes, url: str, host: str
) -> uuid.UUID:
    capture = PageCapture(
        item_version_id=version_id,
        host_id=await ensure(session, host),
        url=url,
        final_url=url,
        status=200,
        outcome=CaptureOutcome.OK,
        body_hash=body[:32],
        body=codec.compress(body, level=12),
    )
    session.add(capture)
    await session.flush()
    return capture.id


@pytest.fixture
def stored_page() -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """A successful capture against a version, without going near the network."""

    async def store(
        version_id: uuid.UUID,
        body: bytes,
        *,
        url: str = "https://www.theguardian.com/society/2026/aug/19/benefits-disabled-young-people",
        host: str = "theguardian.com",
    ) -> uuid.UUID:
        return await _store_capture(version_id, body, url, host)

    return store
