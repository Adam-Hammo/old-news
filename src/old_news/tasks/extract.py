"""Fetching article pages.

Its own queue, so re-running the archive later cannot starve the polls keeping it
current. A sweep rather than something the poll defers: capture is decided by what the
archive is missing, not by what just arrived, so re-capturing an old article runs down
exactly the same path as capturing a new one.
"""

import logging
import uuid

from old_news import extract, fetch, politeness, robots
from old_news.config import get_settings
from old_news.extract import capture, images, service
from old_news.observability import count
from old_news.tasks.app import app
from old_news.tasks.ingest import SCHEDULER_PRIORITY
from old_news.tasks.tracing import defer_unless_queued, task

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
    crawl_delays = await robots.crawl_delays(item.host for item in due)
    delays = politeness.stagger(
        (item.host for item in due),
        minimum=settings.http.min_host_interval_seconds,
        crawl_delays=crawl_delays,
    )

    deferred = 0
    for item, delay in zip(due, delays, strict=True):
        deferred += await defer_unless_queued(
            capture_page.configure(
                # One capture per version in flight. A slow host would otherwise let the
                # sweep stack the same version up behind itself.
                queueing_lock=f"page:{item.version_id}",
                # The article host, which is frequently not the host serving the feed.
                lock=politeness.host_lock(item.host),
                schedule_in={"seconds": delay} if delay else None,
            ),
            version_id=str(item.version_id),
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
    """Extraction touches no network, so it needs no politeness — only its own queue, so
    re-running the archive cannot starve the polls."""
    settings = get_settings()
    due = await extract.due_extractions(settings.extract, settings.extract.extract_batch_size)

    deferred = 0
    for version_id in due:
        deferred += await defer_unless_queued(
            extract_page.configure(queueing_lock=f"extract:{version_id}"),
            version_id=str(version_id),
        )

    if due:
        logger.info("deferred %d of %d due extractions", deferred, len(due))
        count("extract.extractions.deferred", deferred)


@task(app, name="capture_image", queue=QUEUE)
async def capture_image(slot_id: str) -> None:
    await images.capture_image(uuid.UUID(slot_id), fetch.client(), get_settings())


@app.periodic(cron="*/2 * * * *", periodic_id="schedule_lead_images")
@app.task(name="schedule_lead_images", queue=QUEUE, priority=SCHEDULER_PRIORITY)
async def schedule_lead_images(timestamp: int) -> None:
    """Lead images only. Body images are the same task, asked for by a reader rather than
    by a sweep, which is what keeps images from being most of the archive."""
    settings = get_settings()
    due = await images.due_images(settings.extract.image_batch_size)
    hosts = [politeness.host_of(url) for url in await images.hosts_for(due)]
    crawl_delays = await robots.crawl_delays(hosts)
    delays = politeness.stagger(
        hosts, minimum=settings.http.min_host_interval_seconds, crawl_delays=crawl_delays
    )

    deferred = 0
    for slot_id, host, delay in zip(due, hosts, delays, strict=True):
        deferred += await defer_unless_queued(
            capture_image.configure(
                queueing_lock=f"image:{slot_id}",
                lock=politeness.host_lock(host),
                schedule_in={"seconds": delay} if delay else None,
            ),
            slot_id=str(slot_id),
        )

    if due:
        logger.info("deferred %d of %d due images", deferred, len(due))
        count("extract.images.deferred", deferred)
