"""Building items and versions by hand, since a poll is not what is under test here."""

import datetime
import hashlib
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import (
    CAPTURE_POLICY,
    CaptureOutcome,
    Document,
    Extraction,
    ExtractionImage,
    ExtractionSource,
    Feed,
    FeedCapture,
    FeedExtraction,
    Item,
    ItemVersion,
    PageCapture,
    PageExtraction,
    Subscription,
)
from old_news.db import bytes as codec
from old_news.politeness import ensure
from old_news.subscriptions.service import add

from factories import (
    DocumentFields,
    ExtractionFields,
    FeedCaptureFields,
    FeedFields,
    ItemFields,
    ItemVersionFields,
    PageCaptureFields,
    faker,
)

IMAGE_HOST = "loopback.example.com"
PAGE_HOST = "theguardian.com"
PAGE_URL = f"https://www.{PAGE_HOST}/society/2026/aug/19/benefits-disabled-young-people"


@db.transactional
async def _document(session: AsyncSession, feed_id: uuid.UUID) -> uuid.UUID:
    document = Document(feed_id=feed_id, **DocumentFields.kwargs())
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
    # Title and url are what tests assert on; everything else comes from the factory.
    version = ItemVersion(
        item_id=item_id,
        document_id=document_id,
        supersedes_id=supersedes_id,
        observed_at=observed_at,
        **ItemVersionFields.kwargs(title=title, url=url, canonical_url=url),
    )
    session.add(version)
    await session.flush()
    return version.id


@db.transactional
async def _item(session: AsyncSession, feed_id: uuid.UUID) -> uuid.UUID:
    item = Item(feed_id=feed_id, **ItemFields.kwargs())
    session.add(item)
    await session.flush()
    return item.id


@pytest.fixture
def article() -> Callable[..., Coroutine[Any, Any, list[uuid.UUID]]]:
    """An item with one version per title given, chained newest last. `aged` backdates them."""

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
async def version_id(feed_id, article) -> uuid.UUID:
    """The one-version article most of these tests arrange and then read back."""
    return (await article(feed_id, ("A story", "https://loopback.example.com/a")))[0]


@pytest.fixture
async def feed_id() -> uuid.UUID:
    feed = await add("https://loopback.example.com/feed.xml")
    assert feed is not None
    return feed.id


@db.transactional
async def _extraction(
    session: AsyncSession, version_id: uuid.UUID, slots: tuple[tuple[str, str], ...]
) -> list[uuid.UUID]:
    capture = PageCapture(
        item_version_id=version_id,
        host_id=await ensure(session, IMAGE_HOST),
        url=f"https://{IMAGE_HOST}/article",
        body=b"stored",
        **PageCaptureFields.kwargs(),
    )
    session.add(capture)
    await session.flush()

    extraction = PageExtraction(
        item_version_id=version_id,
        page_capture_id=capture.id,
        **ExtractionFields.kwargs(
            source=ExtractionSource.PAGE, extractor="test", extractor_version="0"
        ),
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

    async def build(*slots: tuple[str, str]) -> list[uuid.UUID]:
        version_id = (await article(feed_id, ("An article", f"https://{IMAGE_HOST}/article")))[0]
        return await _extraction(version_id, slots)

    return build


@db.transactional
async def _store_capture(session: AsyncSession, version_id: uuid.UUID, body: bytes) -> uuid.UUID:
    capture = PageCapture(
        item_version_id=version_id,
        host_id=await ensure(session, PAGE_HOST),
        url=PAGE_URL,
        final_url=PAGE_URL,
        body=codec.compress(body, level=12),
        **PageCaptureFields.kwargs(body_hash=hashlib.sha256(body).digest()),
    )
    session.add(capture)
    await session.flush()
    return capture.id


@pytest.fixture
def stored_page() -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """A successful capture against a version, without going near the network."""

    async def store(version_id: uuid.UUID, body: bytes) -> uuid.UUID:
        return await _store_capture(version_id, body)

    return store


@db.transactional
async def _capture(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    status: int,
    ago: datetime.timedelta = datetime.timedelta(0),
    times: int = 1,
    policy: str = CAPTURE_POLICY,
    outcome: str | None = None,
    host: str = "loopback.example.com",
    url: str = "https://loopback.example.com/a",
) -> None:
    host_id = await ensure(session, host)
    if outcome is None:
        outcome = CaptureOutcome.OK if 200 <= status < 300 else CaptureOutcome.FAILED
    for _ in range(times):
        session.add(
            PageCapture(
                item_version_id=version_id,
                host_id=host_id,
                url=url,
                status=status,
                outcome=outcome,
                body_hash=b"0" * 32,
                fetched_at=datetime.datetime.now(datetime.UTC) - ago,
                capture_policy=policy,
            )
        )
    await session.flush()


@pytest.fixture
def captures() -> Callable[..., Awaitable[None]]:
    """Rows in the capture log, without going near the network."""
    return _capture


@db.transactional
async def _store_feed_capture(
    session: AsyncSession, version_id: uuid.UUID, text: str, parser_version: str
) -> uuid.UUID:
    version = await session.get(ItemVersion, version_id)
    assert version is not None
    capture = FeedCapture(
        item_version_id=version_id,
        document_id=version.document_id,
        body=codec.compress(text.encode(), level=12) if text else b"",
        **FeedCaptureFields.kwargs(
            body_hash=hashlib.sha256(text.encode()).digest(), parser_version=parser_version
        ),
    )
    session.add(capture)
    await session.flush()
    return capture.id


@pytest.fixture
def stored_feed_text() -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """What a feed served for a version, carved without going back to the document."""

    async def store(version_id: uuid.UUID, text: str, *, parser_version: str = "test") -> uuid.UUID:
        return await _store_feed_capture(version_id, text, parser_version)

    return store


BYSTANDER_HOST = "bystander.example.com"


@pytest.fixture
def bystander_host() -> str:
    """Named, so a test asserting on an exact set can say which member is not its own."""
    return BYSTANDER_HOST


@db.transactional
async def _bystander(session: AsyncSession) -> None:
    """A second article, settled, that no test is about.

    Its shape varies, so "the newest of" and "across the chain" have something to be wrong
    about. What cannot vary is the current capture policy, parser and extractor — anything
    due here would turn up in every sweep assertion in the suite.
    """
    fake = faker()
    host_id = await ensure(session, BYSTANDER_HOST)
    feed = Feed(host_id=host_id, **FeedFields.kwargs(url=f"https://{BYSTANDER_HOST}/feed.xml"))
    session.add(feed)
    await session.flush()
    session.add(Subscription(feed_id=feed.id, active=True))

    document = Document(feed_id=feed.id, **DocumentFields.kwargs())
    session.add(document)
    await session.flush()

    item = Item(feed_id=feed.id, **ItemFields.kwargs(guid="bystander", identity_key="bystander"))
    session.add(item)
    await session.flush()

    versions: list[ItemVersion] = []
    for _ in range(fake.random_int(1, 3)):
        version = ItemVersion(
            item_id=item.id,
            document_id=document.id,
            supersedes_id=versions[-1].id if versions else None,
            # A distinctive prefix, so a leak is recognisable in the failure and a random
            # sentence can never collide with a phrase some test wrote a rule for.
            **ItemVersionFields.kwargs(
                title=f"Bystander: {fake.sentence()}",
                url=f"https://{BYSTANDER_HOST}/{fake.slug()}",
            ),
        )
        session.add(version)
        await session.flush()
        versions.append(version)

    head = versions[-1]
    body = fake.paragraph(nb_sentences=40)
    # A failure before the answer, so the run of failures this host carries is reset by it.
    for outcome, status in ((CaptureOutcome.FAILED, 0), (CaptureOutcome.OK, 200)):
        capture = PageCapture(
            item_version_id=head.id,
            host_id=host_id,
            url=head.url,
            final_url=head.url,
            body=codec.compress(body.encode(), level=12) if status == 200 else b"",
            **PageCaptureFields.kwargs(outcome=outcome, status=status),
        )
        session.add(capture)
        await session.flush()

    carvings = []
    for text in (fake.paragraph(nb_sentences=5), body):
        carving = FeedCapture(
            item_version_id=head.id,
            document_id=document.id,
            body=codec.compress(text.encode(), level=12),
            **FeedCaptureFields.kwargs(),
        )
        session.add(carving)
        await session.flush()
        carvings.append(carving)

    # Both sources on the head so neither extraction sweep wants it.
    readings: list[Extraction] = [
        PageExtraction(
            item_version_id=head.id,
            page_capture_id=capture.id,
            **ExtractionFields.kwargs(source=ExtractionSource.PAGE, body=body),
        ),
        FeedExtraction(
            item_version_id=head.id,
            feed_capture_id=carvings[-1].id,
            **ExtractionFields.kwargs(body=body),
        ),
    ]
    # And one further back when the chain has a back, so anything reading "the extraction
    # for this item" has a choice it can get wrong. The unique key is per version and
    # source, so a one-version chain must not be given this twice.
    if len(versions) > 1:
        readings.append(
            FeedExtraction(
                item_version_id=versions[0].id,
                feed_capture_id=carvings[0].id,
                **ExtractionFields.kwargs(),
            )
        )
    session.add_all(readings)
    await session.flush()


@pytest.fixture(autouse=True)
async def bystander(clean: None) -> None:
    """Autouse: a test that has to ask for the row catching its own blind spot will not."""
    await _bystander()
