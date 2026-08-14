"""Polling a feed. Orchestration only — the writes live in store.py."""

import datetime
import logging
import uuid
from typing import Any

from sqlalchemy import select

from old_news import db
from old_news.config import IngestSettings, Settings
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher, FetchError, Response
from old_news.ingest import parser, schedule, store
from old_news.observability import count, span

logger = logging.getLogger(__name__)

RATE_LIMITED = {429, 503}


async def due_feed_ids(limit: int) -> list[uuid.UUID]:
    async with db.session() as session:
        rows = await session.execute(
            select(Feed.id)
            .join(Subscription, Subscription.feed_id == Feed.id)
            .where(
                Subscription.active.is_(True),
                Feed.suspended.is_(False),
                Feed.next_poll_at <= datetime.datetime.now(datetime.UTC),
            )
            .order_by(Feed.next_poll_at)
            .limit(limit)
        )
        return list(rows.scalars().all())


def _retry_after(response: Response, settings: IngestSettings) -> int | None:
    """A publisher asking for a pause. Honouring it is how you avoid a block."""
    if response.status not in RATE_LIMITED:
        return None
    raw = response.header("retry-after")
    try:
        # Bounded above as well as below: a server sending 999999999 would
        # otherwise park the feed for decades.
        return min(
            max(int(raw or ""), settings.min_interval_seconds),
            settings.max_interval_seconds,
        )
    except ValueError:
        # The header may be an HTTP date. Backing off by the maximum is fine.
        return settings.max_interval_seconds


async def poll_feed(feed_id: uuid.UUID, fetcher: Fetcher, settings: Settings) -> store.Applied:
    now = datetime.datetime.now(datetime.UTC)

    async with db.session() as session:
        feed = await session.get(Feed, feed_id)
        if feed is None or feed.suspended:
            return store.Applied()
        url, etag, last_modified = feed.url, feed.etag, feed.last_modified

    attributes: dict[str, Any] = {"feed.id": str(feed_id)}
    with span("poll feed", **attributes) as current:
        try:
            response = await fetcher.get(
                url, etag=etag or None, last_modified=last_modified or None
            )
        except FetchError as exc:
            current.record_exception(exc)
            await _record_failure(feed_id, str(exc), settings.ingest, now)
            count("ingest.polls.failed", feed=str(feed_id))
            return store.Applied()

        if response.not_modified:
            await _record_not_modified(feed_id, settings.ingest, now)
            count("ingest.polls.not_modified")
            return store.Applied()

        if not response.ok:
            await _record_failure(
                feed_id,
                f"HTTP {response.status}",
                settings.ingest,
                now,
                status=response.status,
                retry_after=_retry_after(response, settings.ingest),
            )
            count("ingest.polls.failed", feed=str(feed_id))
            return store.Applied()

        try:
            parsed = parser.parse(response.body, url=response.url)
            current.set_attribute("feed.items", len(parsed.items))

            async with db.session() as session:
                feed = await session.get(Feed, feed_id)
                if feed is None:
                    return store.Applied()

                document = await store.record_document(session, feed, response, parsed)
                applied = store.Applied()
                if document is not None:
                    applied = await store.apply_items(
                        session, feed, document, parsed.items, observed_at=now
                    )

                _refresh_feed(feed, parsed, response)
                _reschedule(feed, settings.ingest, now, new_items=applied.new_items)
        except Exception as exc:
            # Without this the schedule never moves, so the feed stays due and the
            # scheduler re-defers it every minute — a hot loop against a publisher
            # whose document happens to break us. Backing off is the same response
            # a fetch failure gets; re-raising still fails the job and the trace.
            current.record_exception(exc)
            await _record_failure(feed_id, f"{type(exc).__name__}: {exc}", settings.ingest, now)
            count("ingest.polls.failed", feed=str(feed_id))
            raise

        count("ingest.items.new", applied.new_items)
        count("ingest.items.edited", applied.new_versions)
        current.set_attribute("feed.new_items", applied.new_items)
        current.set_attribute("feed.new_versions", applied.new_versions)
        return applied


def _refresh_feed(feed: Feed, parsed: parser.ParsedFeed, response: Response) -> None:
    feed.etag = response.etag or ""
    feed.last_modified = response.last_modified or ""
    feed.last_error = ""
    feed.consecutive_failures = 0

    # A feed that has never been named is worth naming; one that has is left
    # alone, because a title edited in Admin should survive a poll.
    if parsed.title and not feed.title:
        feed.title = parsed.title
    feed.description = parsed.description or feed.description
    feed.site_url = parsed.site_url or feed.site_url
    feed.language = parsed.language or feed.language
    feed.icon_url = parsed.icon_url or feed.icon_url
    feed.platform = parsed.platform or feed.platform
    feed.hub_url = parsed.hub_url or feed.hub_url
    feed.ttl_seconds = parsed.ttl_seconds if parsed.ttl_seconds else feed.ttl_seconds
    if parsed.categories:
        feed.categories = list(parsed.categories)


def _reschedule(
    feed: Feed, settings: IngestSettings, now: datetime.datetime, *, new_items: int
) -> None:
    previous = None
    if feed.last_polled_at:
        previous = int((feed.next_poll_at - feed.last_polled_at).total_seconds())

    feed.last_polled_at = now
    feed.last_success_at = now
    feed.next_poll_at = schedule.next_poll_at(
        now,
        settings,
        current_seconds=previous,
        new_items=new_items,
        ttl_seconds=feed.ttl_seconds,
    )


async def _record_not_modified(
    feed_id: uuid.UUID, settings: IngestSettings, now: datetime.datetime
) -> None:
    """A 304: nothing changed, so only the schedule moves."""
    async with db.session() as session:
        feed = await session.get(Feed, feed_id)
        if feed is None:
            return
        feed.consecutive_failures = 0
        feed.last_error = ""
        _reschedule(feed, settings, now, new_items=0)


async def _record_failure(
    feed_id: uuid.UUID,
    reason: str,
    settings: IngestSettings,
    now: datetime.datetime,
    *,
    status: int | None = None,
    retry_after: int | None = None,
) -> None:
    async with db.session() as session:
        feed = await session.get(Feed, feed_id)
        if feed is None:
            return

        feed.consecutive_failures += 1
        feed.last_error = reason[:500]
        feed.last_polled_at = now

        if schedule.should_suspend(settings, failures=feed.consecutive_failures, status=status):
            feed.suspended = True
            feed.suspended_reason = reason[:500]
            logger.warning("suspending feed %s after %s", feed_id, reason)

        if retry_after is not None:
            feed.next_poll_at = now + datetime.timedelta(seconds=retry_after)
            return

        feed.next_poll_at = schedule.next_poll_at(
            now, settings, failures=feed.consecutive_failures, ttl_seconds=feed.ttl_seconds
        )
