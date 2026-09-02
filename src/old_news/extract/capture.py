"""Fetching the page behind a version and keeping the bytes. What it means is elsewhere."""

import hashlib
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, robots
from old_news.config import Settings
from old_news.db import CAPTURE_POLICY, CaptureOutcome, Host, ItemVersion, PageCapture, dictionaries
from old_news.db import bytes as codec
from old_news.extract import breaker
from old_news.fetch import Fetcher, FetchError, Response, Unresolvable
from old_news.observability import count, span
from old_news.politeness import ensure, host_of, with_www

# About a URL, not a publisher: a few dead links must not close a healthy host.
PER_URL_STATUS = frozenset({404, 410})


def _outcome_for(response: Response | None) -> CaptureOutcome:
    """What the answer amounts to for the counting that decides whether to ask again."""
    if response is None:
        return CaptureOutcome.FAILED
    if response.ok:
        return CaptureOutcome.OK
    return CaptureOutcome.GONE if response.status in PER_URL_STATUS else CaptureOutcome.FAILED


@db.transactional
async def _target(session: AsyncSession, version_id: uuid.UUID) -> str | None:
    """The URL to fetch, or None if the version has gone."""
    row = (
        await session.execute(
            select(ItemVersion.url, ItemVersion.canonical_url).where(ItemVersion.id == version_id)
        )
    ).first()
    if row is None:
        return None
    return row.canonical_url or row.url


@db.transactional
async def _host_state(session: AsyncSession, url: str) -> tuple[uuid.UUID, bool] | None:
    """The host row for a URL — its id, and whether its apex is known not to resolve."""
    name = host_of(url)
    if not name:
        return None
    host_id = await ensure(session, name)
    requires_www = (
        await session.execute(select(Host.requires_www).where(Host.id == host_id))
    ).scalar_one()
    return host_id, bool(requires_www)


@db.transactional
async def _learn_www(session: AsyncSession, host_id: uuid.UUID) -> None:
    """Remember that only `www.` answers, so the next capture skips the failure."""
    await session.execute(update(Host).where(Host.id == host_id).values(requires_www=True))


async def _fetch(
    url: str, fetcher: Fetcher, settings: Settings, *, host_id: uuid.UUID
) -> tuple[Response, str]:
    """The page, and the URL it came from. A dead apex is retried once on `www.`."""
    accept = settings.extract.capture_content_types
    try:
        return await fetcher.get(url, accept=accept), url
    except Unresolvable:
        fallback = with_www(url)
        if fallback == url:
            raise
        response = await fetcher.get(fallback, accept=accept)

    await _learn_www(host_id)
    count("extract.captures.www_fallback", host=host_of(fallback))
    return response, fallback


@db.transactional
async def _store(
    session: AsyncSession,
    version_id: uuid.UUID,
    url: str,
    settings: Settings,
    *,
    host_id: uuid.UUID,
    outcome: CaptureOutcome | None = None,
    response: Response | None = None,
    error: str = "",
) -> PageCapture:
    """One row per visit, including the visits we decided not to make."""
    body = response.body if response is not None else b""
    body_hash = hashlib.sha256(body).digest()

    stored = PageCapture(
        item_version_id=version_id,
        host_id=host_id,
        url=url,
        final_url=response.url if response is not None else "",
        status=response.status if response is not None else 0,
        outcome=outcome if outcome is not None else _outcome_for(response),
        body_hash=body_hash,
        headers=_headers(response),
        error=error[:500],
        capture_policy=CAPTURE_POLICY,
    )

    if body:
        # Bytes already held for this URL are pointed at rather than stored twice.
        held = await _held_body(session, url, body_hash)
        if held is None:
            current = await dictionaries.current_for_host(session, host_id)
            stored.body = codec.compress(
                body,
                level=settings.storage.compression_level,
                dictionary=current.dictionary if current else None,
            )
            stored.dictionary_id = current.id if current else None
        else:
            stored.body, stored.dictionary_id = held

    session.add(stored)
    await session.flush()
    return stored


async def _held_body(
    session: AsyncSession, url: str, body_hash: bytes
) -> tuple[bytes, uuid.UUID | None] | None:
    row = (
        await session.execute(
            select(PageCapture.body, PageCapture.dictionary_id)
            .where(PageCapture.url == url, PageCapture.body_hash == body_hash)
            .limit(1)
        )
    ).first()
    return (row.body, row.dictionary_id) if row else None


def _headers(response: Response | None) -> dict[str, str]:
    if response is None:
        return {}
    captured = ("content-type", "etag", "last-modified", "content-length", "cache-control")
    return {name: value for name in captured if (value := response.header(name))}


async def capture_page(
    version_id: uuid.UUID, fetcher: Fetcher, settings: Settings
) -> PageCapture | None:
    """Read the target, fetch it, write what came back. No transaction spans the fetch."""
    url = await _target(version_id)
    if url is None:
        return None

    state = await _host_state(url)
    if state is None:
        return None
    host_id, requires_www = state
    target = with_www(url) if requires_www else url

    attributes: dict[str, Any] = {"version.id": str(version_id)}
    with span("capture page", **attributes) as current:
        # Checked here as well as in the sweep, for a job queued before a rule existed.
        # Each spends a batch slot without sending a request, so each records one — and
        # none counts as the publisher failing, so recording cannot move the breaker.
        if not await robots.rules_known(target):
            current.set_attribute("page.rules_unknown", True)
            count("extract.captures.rules_unknown", host=host_of(target))
            return await _store(
                version_id,
                target,
                settings,
                host_id=host_id,
                outcome=CaptureOutcome.UNKNOWN_RULES,
                error="robots.txt never read",
            )

        if not await robots.allows(target, settings):
            current.set_attribute("page.disallowed", True)
            count("extract.captures.disallowed", host=host_of(target))
            return await _store(
                version_id,
                target,
                settings,
                host_id=host_id,
                outcome=CaptureOutcome.DISALLOWED,
                error="disallowed by robots.txt",
            )

        if await breaker.refusing_host(host_id, settings.extract):
            current.set_attribute("page.host_refusing", True)
            count("extract.captures.host_refusing", host=host_of(target))
            return await _store(
                version_id,
                target,
                settings,
                host_id=host_id,
                outcome=CaptureOutcome.REFUSED,
                error="host refusing",
            )

        try:
            response, target = await _fetch(target, fetcher, settings, host_id=host_id)
        except FetchError as exc:
            current.record_exception(exc)
            count("extract.captures.failed", host=host_of(target))
            return await _store(version_id, target, settings, host_id=host_id, error=str(exc))

        current.set_attribute("http.response.status_code", response.status)

        # Redirects are followed inside the fetch, so only the first host was asked.
        if not await robots.allows_after_redirect(target, response.url, settings):
            current.set_attribute("page.redirect_disallowed", True)
            count("extract.captures.redirect_disallowed", host=host_of(response.url))
            return await _store(
                version_id,
                target,
                settings,
                host_id=host_id,
                outcome=CaptureOutcome.DISALLOWED,
                error=f"redirected to {host_of(response.url)}",
            )

        count("extract.captures.stored" if response.ok else "extract.captures.failed")
        return await _store(version_id, target, settings, host_id=host_id, response=response)
