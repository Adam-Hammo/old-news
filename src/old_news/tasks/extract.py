"""Fetching article pages, on its own queue, driven by what the archive is missing."""

import logging
import uuid

from old_news import extract, fetch
from old_news.config import get_settings
from old_news.extract import capture, encode, feed, images, service
from old_news.observability import count
from old_news.tasks import sweep
from old_news.tasks.app import app
from old_news.tasks.ingest import SCHEDULER_PRIORITY
from old_news.tasks.tracing import task

logger = logging.getLogger(__name__)

QUEUE = "pages"


@task(app, name="capture_page", queue=QUEUE)
async def capture_page(version_id: str) -> None:
    """Takes an identifier, never a URL: procrastinate logs kwargs at INFO."""
    await capture.capture_page(uuid.UUID(version_id), fetch.client(), get_settings())


@app.periodic(cron="* * * * *", periodic_id="schedule_captures")
@app.task(name="schedule_captures", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_captures(timestamp: int) -> None:
    settings = get_settings()
    due = await extract.due_captures(settings.extract, settings.extract.capture_batch_size)
    deferred = await sweep.defer_each(
        capture_page,
        [item.version_id for item in due],
        kwarg="version_id",
        lock_prefix="page",
        # The article host, which is frequently not the host serving the feed.
        hosts=[item.host for item in due],
        min_host_interval_seconds=settings.http.min_host_interval_seconds,
    )

    if due:
        logger.info("deferred %d of %d due captures", deferred, len(due))
        count("extract.captures.deferred", deferred)
        count("extract.captures.already_queued", len(due) - deferred)


@task(app, name="extract_page", queue=QUEUE)
async def extract_page(version_id: str) -> None:
    await service.extract_page(uuid.UUID(version_id), get_settings().extract)


@app.periodic(cron="*/2 * * * *", periodic_id="schedule_extractions")
@app.task(name="schedule_extractions", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_extractions(timestamp: int) -> None:
    """No network, so no politeness — only its own queue."""
    settings = get_settings()
    due = await extract.due_extractions(settings.extract, settings.extract.extract_batch_size)
    deferred = await sweep.defer_each(extract_page, due, kwarg="version_id", lock_prefix="extract")

    if due:
        logger.info("deferred %d of %d due extractions", deferred, len(due))
        count("extract.extractions.deferred", deferred)


@task(app, name="capture_feed", queue=QUEUE)
async def capture_feed(document_id: str) -> None:
    await feed.capture_feed(uuid.UUID(document_id), get_settings())


@app.periodic(cron="*/2 * * * *", periodic_id="schedule_feed_captures")
@app.task(name="schedule_feed_captures", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_feed_captures(timestamp: int) -> None:
    """One job per document, not per version: the parse is what costs, and it is shared."""
    settings = get_settings()
    due = await extract.due_feed_captures(settings.extract.extract_batch_size)
    deferred = await sweep.defer_each(
        capture_feed, due, kwarg="document_id", lock_prefix="capture-feed"
    )

    if due:
        logger.info("deferred %d of %d due feed captures", deferred, len(due))
        count("extract.feed_captures.deferred", deferred)


@task(app, name="extract_feed", queue=QUEUE)
async def extract_feed(version_id: str) -> None:
    await service.extract_feed(uuid.UUID(version_id), get_settings().extract)


@app.periodic(cron="*/2 * * * *", periodic_id="schedule_feed_extractions")
@app.task(name="schedule_feed_extractions", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_feed_extractions(timestamp: int) -> None:
    """Newest first, unlike the page sweep: this costs no request, so fairness is moot."""
    settings = get_settings()
    due = await extract.due_feed_extractions(settings.extract.extract_batch_size)
    deferred = await sweep.defer_each(
        extract_feed, due, kwarg="version_id", lock_prefix="extract-feed"
    )

    if due:
        logger.info("deferred %d of %d due feed extractions", deferred, len(due))
        count("extract.feed_extractions.deferred", deferred)


@task(app, name="capture_image", queue=QUEUE)
async def capture_image(slot_id: str) -> None:
    await images.capture_image(uuid.UUID(slot_id), fetch.client(), get_settings())


@app.periodic(cron="*/2 * * * *", periodic_id="schedule_lead_images")
@app.task(name="schedule_lead_images", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_lead_images(timestamp: int) -> None:
    """Every lead, unconditionally: it is the one picture a card or a page needs."""
    settings = get_settings()
    due = await images.due_images(settings.extract.image_batch_size)
    deferred = await sweep.defer_each(
        capture_image,
        due,
        kwarg="slot_id",
        lock_prefix="image",
        hosts=await images.hosts_for(due),
        min_host_interval_seconds=settings.http.min_host_interval_seconds,
    )

    if due:
        logger.info("deferred %d of %d due images", deferred, len(due))
        count("extract.images.deferred", deferred)


@app.periodic(cron="*/5 * * * *", periodic_id="schedule_body_images")
@app.task(name="schedule_body_images", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_body_images(timestamp: int) -> None:
    """The rest of an article's pictures, for the feeds worth holding them for."""
    settings = get_settings()
    due = await extract.due_body_images(settings.extract.image_batch_size)
    deferred = await sweep.defer_each(
        capture_image,
        due,
        kwarg="slot_id",
        lock_prefix="image",
        hosts=await images.hosts_for(due),
        min_host_interval_seconds=settings.http.min_host_interval_seconds,
    )

    if due:
        logger.info("deferred %d of %d due body images", deferred, len(due))
        count("extract.body_images.deferred", deferred)


@task(app, name="encode_image", queue=QUEUE)
async def encode_image(capture_id: str) -> None:
    await encode.encode_image(uuid.UUID(capture_id), get_settings().extract)


@app.periodic(cron="*/5 * * * *", periodic_id="schedule_encodes")
@app.task(name="schedule_encodes", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_encodes(timestamp: int) -> None:
    """No network, so no politeness. Biggest images first, which is where the bytes are."""
    settings = get_settings()
    due = await extract.due_encodes(settings.extract, settings.extract.encode_batch_size)
    deferred = await sweep.defer_each(encode_image, due, kwarg="capture_id", lock_prefix="encode")

    if due:
        logger.info("deferred %d of %d due image encodes", deferred, len(due))
        count("extract.images.encodes_deferred", deferred)
