"""Fetching the page behind a version and keeping the bytes.

Capture only. What the page means is derived, disposable and lands in its own table, so a
wrong extractor costs a rerun rather than the article.
"""

import datetime
import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, robots
from old_news.config import Settings
from old_news.db import Host, ItemVersion, PageCapture, dictionaries
from old_news.db import bytes as codec
from old_news.extract import breaker
from old_news.fetch import Fetcher, FetchError, Response, Unresolvable
from old_news.observability import count, span
from old_news.politeness import ensure, host_of, with_www

logger = logging.getLogger(__name__)

# A transport failure is not an HTTP status, and 0 is not one either.
NO_STATUS = 0


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
    learned = (
        await session.execute(select(Host.www_learned_at).where(Host.id == host_id))
    ).scalar_one()
    return host_id, learned is not None


@db.transactional
async def _learn_www(session: AsyncSession, host_id: uuid.UUID) -> None:
    """Remember that only the `www.` name answers, so the next capture goes straight
    there. Observed, and reversed by nothing: if they add the record we simply keep
    using a name that works.

    Only ever written once. The timestamp is what the capture sweep counts refusals
    from, so moving it would forgive the same failures again and retry without end.
    """
    await session.execute(
        update(Host)
        .where(Host.id == host_id, Host.www_learned_at.is_(None))
        .values(www_learned_at=datetime.datetime.now(datetime.UTC))
    )


async def _fetch(
    url: str, fetcher: Fetcher, settings: Settings, *, host_id: uuid.UUID
) -> tuple[Response, str]:
    """The page, and the URL it actually came from.

    A publisher whose apex has no DNS record is asked again on the `www.` name before
    being written off — that is one feed in this corpus, not a hypothetical.
    """
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
    response: Response | None = None,
    error: str = "",
) -> PageCapture:
    """One row per attempt. A failure is a fact about the archive, so it is recorded
    rather than thrown away, and the row is what bounds the next retry."""
    body = response.body if response is not None else b""
    body_hash = hashlib.sha256(body).digest()
    host_id = await ensure(session, host_of(url))

    stored = PageCapture(
        item_version_id=version_id,
        host_id=host_id,
        url=url,
        final_url=response.url if response is not None else "",
        status=response.status if response is not None else NO_STATUS,
        body_hash=body_hash,
        headers=_headers(response),
        error=error[:500],
    )

    if body:
        # Bytes already held for this URL are pointed at rather than stored twice: 204
        # URLs in this corpus arrive in more than one feed.
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
    # Learned last time, so the attempt that taught us is not repeated per article.
    target = with_www(url) if requires_www else url

    attributes: dict[str, Any] = {"version.id": str(version_id)}
    with span("capture page", **attributes) as current:
        # Checked here as well as in the sweep: a job queued before a rule existed, or
        # a re-capture asked for by hand, must not slip past it.
        if not await robots.rules_known(target):
            current.set_attribute("page.rules_unknown", True)
            count("extract.captures.rules_unknown", host=host_of(target))
            return None

        if not await robots.allows(target, settings):
            current.set_attribute("page.disallowed", True)
            count("extract.captures.disallowed", host=host_of(target))
            return None

        # Deciding not to fetch is not an attempt, so nothing is stored — the same shape
        # as the two checks above. A stored row here would also poison the window the
        # breaker reads, which is the thing deciding whether to ask again at all.
        if await breaker.refusing(host_id, settings.extract):
            current.set_attribute("page.host_refusing", True)
            count("extract.captures.host_refusing", host=host_of(target))
            return None

        try:
            response, target = await _fetch(target, fetcher, settings, host_id=host_id)
        except FetchError as exc:
            current.record_exception(exc)
            count("extract.captures.failed", host=host_of(target))
            return await _store(version_id, target, settings, error=str(exc))

        current.set_attribute("http.response.status_code", response.status)

        # Redirects are followed inside the fetch, so only the first host was checked. A
        # hop to somewhere else has said nothing about us, and its bytes are not archived
        # on the strength of a permission another publisher gave.
        if not await robots.allows_after_redirect(target, response.url, settings):
            current.set_attribute("page.redirect_disallowed", True)
            count("extract.captures.redirect_disallowed", host=host_of(response.url))
            return await _store(
                version_id, target, settings, error=f"redirected to {host_of(response.url)}"
            )

        count("extract.captures.stored" if response.ok else "extract.captures.failed")
        return await _store(version_id, target, settings, response=response)
