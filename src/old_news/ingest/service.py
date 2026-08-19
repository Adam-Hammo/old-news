"""Polling a feed. Orchestration only — the writes live in store.py.

Each transaction is its own decorated function; `poll_feed` is the network half,
deliberately inside none of them.
"""

import dataclasses
import datetime
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, robots
from old_news.config import IngestSettings, Settings
from old_news.db import Feed, Host
from old_news.fetch import Fetcher, FetchError, Response
from old_news.ingest import parser, schedule, store
from old_news.observability import count, span

logger = logging.getLogger(__name__)

RATE_LIMITED = {429, 503}


@dataclasses.dataclass(frozen=True, slots=True)
class DuePoll:
    """A feed to visit, and the host politeness groups it under.

    The host travels rather than the URL, which can carry an API key.
    """

    feed_id: uuid.UUID
    host: str


@dataclasses.dataclass(frozen=True, slots=True)
class _FetchState:
    """The feed row's fetch inputs, copied out so the transaction closes first."""

    url: str
    etag: str
    last_modified: str


@db.transactional
async def due_polls(session: AsyncSession, limit: int) -> list[DuePoll]:
    rows = await session.execute(
        select(Feed.id, Host.name)
        .join(Host, Host.id == Feed.host_id)
        .where(
            Feed.subscribed,
            Feed.suspended.is_(False),
            Feed.next_poll_at <= datetime.datetime.now(datetime.UTC),
        )
        .order_by(Feed.next_poll_at)
        .limit(limit)
    )
    return [DuePoll(feed_id, name) for feed_id, name in rows.all()]


@db.transactional
async def subscribed_hosts(session: AsyncSession) -> list[str]:
    """Every host we currently poll. What robots.txt refreshes are driven from."""
    rows = await session.execute(
        select(Host.name)
        .distinct()
        .join(Feed, Feed.host_id == Host.id)
        .where(Feed.subscribed, Feed.suspended.is_(False))
    )
    return sorted(name for (name,) in rows.all())


@db.transactional
async def _fetch_state(session: AsyncSession, feed_id: uuid.UUID) -> _FetchState | None:
    """None when there is nothing to poll — the feed is gone or suspended."""
    feed = await session.get(Feed, feed_id)
    if feed is None or feed.suspended:
        return None
    return _FetchState(feed.url, feed.etag, feed.last_modified)


@db.transactional
async def _store_poll(
    session: AsyncSession,
    feed_id: uuid.UUID,
    response: Response,
    parsed: parser.ParsedFeed,
    settings: Settings,
    now: datetime.datetime,
) -> store.Applied | None:
    """The write half of a poll, in one transaction: it lands whole or not at all."""
    feed = await session.get(Feed, feed_id)
    if feed is None:
        return None

    document = await store.record_document(session, feed, response, parsed, settings.storage)
    applied = store.Applied()
    if document is not None:
        applied = await store.apply_items(session, feed, document, parsed.items, observed_at=now)

    _refresh_feed(feed, parsed, response)
    _reschedule(feed, settings.ingest, now, new_items=applied.new_items)
    return applied


@db.transactional
async def _record_disallowed(
    session: AsyncSession, feed_id: uuid.UUID, settings: IngestSettings, now: datetime.datetime
) -> None:
    """robots.txt names this feed. Backed off rather than suspended and not counted
    as a failure, so dropping the rule brings the feed back on its own."""
    feed = await session.get(Feed, feed_id)
    if feed is None:
        return
    feed.last_polled_at = now
    feed.last_error = "disallowed by robots.txt"
    feed.next_poll_at = now + datetime.timedelta(seconds=settings.max_interval_seconds)


@db.transactional
async def _record_not_modified(
    session: AsyncSession, feed_id: uuid.UUID, settings: IngestSettings, now: datetime.datetime
) -> None:
    """A 304: nothing changed, so only the schedule moves."""
    feed = await session.get(Feed, feed_id)
    if feed is None:
        return
    feed.consecutive_failures = 0
    feed.last_error = ""
    _reschedule(feed, settings, now, new_items=0)


@db.transactional
async def _record_failure(
    session: AsyncSession,
    feed_id: uuid.UUID,
    reason: str,
    settings: IngestSettings,
    now: datetime.datetime,
    *,
    status: int | None = None,
    retry_after: int | None = None,
) -> None:
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


def _retry_after(response: Response, settings: IngestSettings) -> int | None:
    """A publisher asking for a pause. Honouring it is how you avoid a block."""
    if response.status not in RATE_LIMITED:
        return None
    raw = response.header("retry-after")
    try:
        # Bounded above as well as below: a server sending 999999999 would
        # otherwise park the feed for decades.
        return schedule.clamp_interval(int(raw or ""), settings)
    except ValueError:
        # The header may be an HTTP date. Backing off by the maximum is fine.
        return settings.max_interval_seconds


async def poll_feed(feed_id: uuid.UUID, fetcher: Fetcher, settings: Settings) -> store.Applied:
    """Read state, fetch, write state. No transaction is open across the fetch."""
    now = datetime.datetime.now(datetime.UTC)

    state = await _fetch_state(feed_id)
    if state is None:
        return store.Applied()

    attributes: dict[str, Any] = {"feed.id": str(feed_id)}
    with span("poll feed", **attributes) as current:
        if not await robots.allows_poll(state.url, settings):
            current.set_attribute("feed.disallowed", True)
            await _record_disallowed(feed_id, settings.ingest, now)
            count("ingest.polls.disallowed", feed=str(feed_id))
            return store.Applied()

        try:
            response = await fetcher.get(
                state.url, etag=state.etag or None, last_modified=state.last_modified or None
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
            applied = await _store_poll(feed_id, response, parsed, settings, now)
        except Exception as exc:
            # Without this the schedule never moves, so the feed stays due and the
            # scheduler re-defers it every minute — a hot loop against a publisher
            # whose document happens to break us. Backing off is the same response
            # a fetch failure gets; re-raising still fails the job and the trace.
            current.record_exception(exc)
            await _record_failure(feed_id, f"{type(exc).__name__}: {exc}", settings.ingest, now)
            count("ingest.polls.failed", feed=str(feed_id))
            raise

        if applied is None:
            return store.Applied()

        count("ingest.items.new", applied.new_items)
        count("ingest.items.edited", applied.new_versions)
        # Both were computed and then dropped on the floor. A publisher rewriting
        # its guids is a platform move, and a feed repeating one is broken.
        count("ingest.items.guid_churn", applied.guid_churn)
        count("ingest.items.duplicate_identity", applied.duplicate_identity)
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
