"""The page sweeps: what each one defers, and how politely."""

import datetime
import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import (
    Document,
    ExtractionImage,
    Feed,
    FeedCapture,
    FeedExtraction,
    ImageCapture,
    ImageRole,
    Item,
    ItemVersion,
    PageCapture,
    RobotsPolicy,
    Subscription,
)
from old_news.db import bytes as codec
from old_news.extract.images import digest_of
from old_news.politeness import ensure
from old_news.tasks import extract as extract_tasks
from old_news.tasks.extract import (
    schedule_captures,
    schedule_encodes,
    schedule_extractions,
    schedule_feed_captures,
    schedule_feed_extractions,
    schedule_lead_images,
)

from factories import (
    DocumentFields,
    ExtractionFields,
    FeedCaptureFields,
    FeedFields,
    ItemFields,
    ItemVersionFields,
    PageCaptureFields,
)

# Nothing is published from the host serving the feed, so a sweep keyed on the wrong
# one of the two shows up as a lock nothing else takes.
FEED_HOST = "feeds.example.com"
ARTICLE = "https://www.theguardian.com/uk-news/a"


@pytest.fixture(autouse=True)
def own_settings(settings, monkeypatch) -> None:
    """Each sweep resolves `get_settings` from its own module, not the ingest one."""
    monkeypatch.setattr(extract_tasks, "get_settings", lambda: settings)


async def _jobs(task_name: str) -> list:
    async with db.session() as session:
        rows = await session.execute(
            text(
                "SELECT args, lock, queueing_lock, scheduled_at FROM procrastinate_jobs "
                "WHERE task_name = :task ORDER BY id"
            ),
            {"task": task_name},
        )
        return list(rows.all())


@db.transactional
async def _articles(session: AsyncSession, *urls: str) -> list[uuid.UUID]:
    """A followed feed and a head version per URL, each on an item chain of its own."""
    feed = Feed(
        host_id=await ensure(session, FEED_HOST),
        **FeedFields.kwargs(url=f"https://{FEED_HOST}/feed.xml"),
    )
    session.add(feed)
    await session.flush()
    session.add(Subscription(feed_id=feed.id, active=True))

    document = Document(feed_id=feed.id, **DocumentFields.kwargs())
    session.add(document)
    await session.flush()

    made: list[uuid.UUID] = []
    for url in urls:
        item = Item(feed_id=feed.id, **ItemFields.kwargs())
        session.add(item)
        await session.flush()
        version = ItemVersion(
            item_id=item.id, document_id=document.id, **ItemVersionFields.kwargs(url=url)
        )
        session.add(version)
        await session.flush()
        made.append(version.id)
    return made


@db.transactional
async def _rules_read(session: AsyncSession, *hosts: str) -> None:
    """An answer on record, which is what the capture sweep waits for before asking."""
    now = datetime.datetime.now(datetime.UTC)
    for host in hosts:
        session.add(
            RobotsPolicy(
                host_id=await ensure(session, host),
                status=200,
                fetched_at=now,
                expires_at=now + datetime.timedelta(hours=6),
            )
        )


async def test_a_due_page_is_deferred_under_the_host_publishing_it(
    no_jobs: None, no_policies: None, queue_app, settings
):
    """Three articles from one publisher and one from another, keyed on the article host."""
    *guardian, bbc = await _articles(
        "https://www.theguardian.com/uk-news/a",
        "https://www.theguardian.com/uk-news/b",
        "https://www.theguardian.com/uk-news/c",
        "https://www.bbc.co.uk/news/d",
    )
    await _rules_read("theguardian.com", "bbc.co.uk")

    async with queue_app.open_async():
        await schedule_captures(timestamp=0)

    jobs = await _jobs("capture_page")
    held: dict[str, list] = {}
    for job in jobs:
        held.setdefault(job.lock, []).append(job.scheduled_at)

    assert {job.args["version_id"] for job in jobs} == {str(v) for v in [*guardian, bbc]}
    assert {job.queueing_lock for job in jobs} == {f"page:{v}" for v in [*guardian, bbc]}
    assert held["host:bbc.co.uk"] == [None]

    spaced = held["host:theguardian.com"]
    gap = settings.http.min_host_interval_seconds
    assert len(spaced) == 3
    assert spaced[0] is None
    assert (spaced[2] - spaced[1]).total_seconds() == pytest.approx(gap, abs=1.0)


@db.transactional
async def _lead_slots(session: AsyncSession, version_id: uuid.UUID, *urls: str) -> list[uuid.UUID]:
    """Lead slots with nothing fetched against them, which is all that sweep looks at."""
    version = await session.get(ItemVersion, version_id)
    assert version is not None
    capture = FeedCapture(
        item_version_id=version_id,
        document_id=version.document_id,
        body=b"",
        **FeedCaptureFields.kwargs(),
    )
    session.add(capture)
    await session.flush()

    extraction = FeedExtraction(
        item_version_id=version_id, feed_capture_id=capture.id, **ExtractionFields.kwargs()
    )
    session.add(extraction)
    await session.flush()

    made: list[uuid.UUID] = []
    for position, url in enumerate(urls):
        slot = ExtractionImage(
            extraction_id=extraction.id, url=url, role=ImageRole.LEAD, position=position
        )
        session.add(slot)
        await session.flush()
        made.append(slot.id)
    return made


async def test_each_image_slot_is_deferred_under_the_host_serving_it(
    no_jobs: None, queue_app, settings
):
    """Slots and hosts are paired by position, so a misalignment lands as the wrong lock."""
    (version_id,) = await _articles(ARTICLE)
    slots = await _lead_slots(
        version_id,
        "https://i.guim.co.uk/one.jpg",
        "https://i.guim.co.uk/two.jpg",
        "https://ichef.bbci.co.uk/three.jpg",
    )

    before = datetime.datetime.now(datetime.UTC)
    async with queue_app.open_async():
        await schedule_lead_images(timestamp=0)

    jobs = await _jobs("capture_image")

    assert [job.args["slot_id"] for job in jobs] == [str(slot) for slot in slots]
    assert [job.queueing_lock for job in jobs] == [f"image:{slot}" for slot in slots]
    assert [job.lock for job in jobs] == [
        "host:i.guim.co.uk",
        "host:i.guim.co.uk",
        "host:ichef.bbci.co.uk",
    ]

    gap = settings.http.min_host_interval_seconds
    assert (jobs[0].scheduled_at, jobs[2].scheduled_at) == (None, None)
    assert (jobs[1].scheduled_at - before).total_seconds() == pytest.approx(gap, abs=1.0)


IMAGE_URL = "https://i.guim.co.uk/lead.jpg"
IMAGE_BODY = b"not really a jpeg, but bytes are bytes"


@db.transactional
async def _due_everywhere(session: AsyncSession, version_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Artefacts around one version that every sweep taking no host lock has work on."""
    version = await session.get(ItemVersion, version_id)
    assert version is not None
    host_id = await ensure(session, "theguardian.com")

    session.add(
        PageCapture(
            item_version_id=version_id,
            host_id=host_id,
            url=version.url,
            body=codec.compress(b"<html>a page</html>", level=12),
            **PageCaptureFields.kwargs(),
        )
    )
    # Carved by a parser we no longer run, so the text is stale and present at once: the
    # document is due for reading again and the version has something to extract from.
    session.add(
        FeedCapture(
            item_version_id=version_id,
            document_id=version.document_id,
            body=codec.compress(b"a paragraph", level=12),
            **FeedCaptureFields.kwargs(parser_version="stale"),
        )
    )
    capture = ImageCapture(
        url=IMAGE_URL,
        url_digest=digest_of(IMAGE_URL),
        host_id=host_id,
        status=200,
        content_type="image/jpeg",
        body=IMAGE_BODY,
        body_hash=hashlib.sha256(IMAGE_BODY).digest(),
        byte_size=len(IMAGE_BODY),
    )
    session.add(capture)
    await session.flush()

    return {
        "version_id": version_id,
        "document_id": version.document_id,
        "capture_id": capture.id,
    }


SWEEPS = (
    (schedule_extractions, "extract_page", "extract", "version_id"),
    (schedule_feed_captures, "capture_feed", "capture-feed", "document_id"),
    (schedule_feed_extractions, "extract_feed", "extract-feed", "version_id"),
    (schedule_encodes, "encode_image", "encode", "capture_id"),
)


@pytest.mark.parametrize(
    ("sweep", "task_name", "lock_prefix", "kwarg"), SWEEPS, ids=[row[1] for row in SWEEPS]
)
async def test_a_sweep_needing_no_network_defers_one_unlocked_job(
    sweep, task_name: str, lock_prefix: str, kwarg: str, no_jobs: None, queue_app
):
    """Four sweeps over one archive: each defers its own subject and nothing else's."""
    due = await _due_everywhere((await _articles(ARTICLE))[0])

    async with queue_app.open_async():
        await sweep(timestamp=0)

    jobs = await _jobs(task_name)

    assert len(jobs) == 1
    assert jobs[0].args[kwarg] == str(due[kwarg])
    assert jobs[0].queueing_lock == f"{lock_prefix}:{due[kwarg]}"
    # No host to be polite about, so nothing serialises and nothing is held back.
    assert (jobs[0].lock, jobs[0].scheduled_at) == (None, None)
