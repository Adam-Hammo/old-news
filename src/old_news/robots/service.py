"""Fetching, storing and answering robots.txt.

Unreachable means carry on: a publisher that couldn't state its rules hasn't
prohibited anything, and failing closed would stop the archive on every CDN hiccup.
"""

import datetime
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import Settings
from old_news.db import Host, RobotsPolicy
from old_news.fetch import Fetcher, FetchError
from old_news.observability import count, span
from old_news.politeness import ensure, host_of
from old_news.robots.parse import Rules, allow_everything, parse

logger = logging.getLogger(__name__)

# 404 means no rules exist. 5xx means the host is broken, which is not consent to
# hammer it — but it is not a prohibition either, so both allow and both get
# retried on the shorter clock.
UNREACHABLE_STATUS = 0


def _robots_url(host: str) -> str:
    """https only; an http-only host fails the fetch and is carried on past."""
    return f"https://{host}/robots.txt"


@db.transactional
async def _store_policy(session: AsyncSession, host: str, values: dict[str, Any]) -> RobotsPolicy:
    """Upsert, so two sweeps racing on one host cannot both insert."""
    keyed = {"host_id": await ensure(session, host), **values}
    stored = await session.execute(
        insert(RobotsPolicy)
        .values(**keyed)
        .on_conflict_do_update(index_elements=["host_id"], set_=keyed)
        .returning(RobotsPolicy)
    )
    return stored.scalar_one()


async def refresh(
    host: str, fetcher: Fetcher, settings: Settings, *, origin: str | None = None
) -> RobotsPolicy:
    """Fetch one host's robots.txt and store what it said.

    `origin` moves where it is fetched from without changing which host it is filed
    under, so this can be tested against a loopback socket.
    """
    robots = settings.robots
    now = datetime.datetime.now(datetime.UTC)
    body, status, error = "", UNREACHABLE_STATUS, ""
    url = f"{origin.rstrip('/')}/robots.txt" if origin else _robots_url(host)

    attributes: dict[str, Any] = {"robots.host": host}
    with span("fetch robots", **attributes) as current:
        try:
            response = await fetcher.get(url)
            status = response.status
            if response.ok and host_of(response.url) != host_of(url):
                # A cross-host redirect would file another publisher's rules under this
                # host — and those rules could *grant* what this one forbade. Treated as
                # unreachable, which allows but keeps asking, rather than as an answer.
                error = f"robots.txt redirected to {host_of(response.url)}"
                status = UNREACHABLE_STATUS
                count("robots.redirected_away", host=host)
            elif response.ok:
                # Truncated, not rejected: a body over the limit still has rules
                # at the top, and everything past the cut is not a rule anyway.
                body = response.body[: robots.max_body_bytes].decode("utf-8", errors="replace")
        except FetchError as exc:
            error = str(exc)[:500]
            current.record_exception(exc)

        current.set_attribute("http.response.status_code", status)

    rules = _rules(body, settings)
    answered = 200 <= status < 300
    ttl = robots.ttl_seconds if answered else robots.failure_ttl_seconds

    count("robots.refreshed", host=host, answered=answered)
    if rules.crawl_delay:
        logger.info("%s asks for %ss between requests", host, rules.crawl_delay)

    # One row per host, overwritten.
    return await _store_policy(
        host,
        {
            "body": body,
            "status": status,
            "error": error,
            "crawl_delay_seconds": rules.crawl_delay,
            "fetched_at": now,
            "expires_at": now + datetime.timedelta(seconds=ttl),
        },
    )


def _rules(body: str, settings: Settings) -> Rules:
    """One place deciding which agent we are — the token in the User-Agent header."""
    return parse(
        body,
        user_agent=settings.http.user_agent,
        max_crawl_delay=settings.robots.max_crawl_delay_seconds,
    )


@db.transactional
async def _stored_body(session: AsyncSession, host: str) -> str | None:
    return (
        await session.execute(
            select(RobotsPolicy.body)
            .join(Host, Host.id == RobotsPolicy.host_id)
            .where(Host.name == host)
        )
    ).scalar_one_or_none()


async def _rules_for(host: str, settings: Settings) -> Rules:
    """The stored rules for a host, or allow-everything if none are stored yet.

    Never fetches: that would make robots.txt a dependency of every request rather
    than of a periodic job.
    """
    body = await _stored_body(host)
    if body is None:
        return allow_everything(settings.http.user_agent)
    return _rules(body, settings)


@db.transactional
async def _has_policy(session: AsyncSession, host: str) -> bool:
    return (
        await session.execute(
            select(RobotsPolicy.id)
            .join(Host, Host.id == RobotsPolicy.host_id)
            .where(Host.name == host)
        )
    ).first() is not None


async def allows_after_redirect(requested: str, final: str, settings: Settings) -> bool:
    """Whether a fetch that ended somewhere else may be archived.

    `follow_redirects` is on, so up to five hops happen inside one call and only the first
    host was ever checked. Same host is the ordinary case — `theguardian.com` sending you
    to `www.theguardian.com` is not a redirect worth the word. A different one has said
    nothing about us, so it is asked the same two questions as any other.
    """
    if host_of(final) == host_of(requested):
        return True
    return await rules_known(final) and await allows(final, settings)


async def rules_known(url: str) -> bool:
    """Whether this host's robots.txt has been asked for, whatever it said.

    `allows` treats unknown rules as permission, which is right for a feed published for
    readers and wrong for crawling a publisher's pages. Anything doing the latter checks
    this first.
    """
    host = host_of(url)
    return not host or await _has_policy(host)


async def allows(url: str, settings: Settings) -> bool:
    """Whether a URL may be fetched. The check to make before an article fetch."""
    host = host_of(url)
    if not host:
        return True
    rules = await _rules_for(host, settings)
    allowed = rules.allows(url)
    if not allowed:
        count("robots.disallowed", host=host, kind="article")
    return allowed


@db.transactional
async def _stored_delays(session: AsyncSession, hosts: set[str]) -> dict[str, float]:
    rows = await session.execute(
        select(Host.name, RobotsPolicy.crawl_delay_seconds)
        .join(RobotsPolicy, RobotsPolicy.host_id == Host.id)
        .where(Host.name.in_(hosts), RobotsPolicy.crawl_delay_seconds.is_not(None))
    )
    return {name: float(delay) for name, delay in rows.all() if delay is not None}


async def allows_poll(url: str, settings: Settings) -> bool:
    """Whether a feed may be polled.

    Stricter than nothing and looser than `allows`: a rule naming this feed is
    obeyed, but a blanket `Disallow: /` is not. RSS is published for readers, so a
    site that ships a feed and bans all bots is stating a crawler policy, not
    withdrawing the feed.
    """
    host = host_of(url)
    if not host:
        return True

    rules = await _rules_for(host, settings)
    if rules.allows(url):
        return True
    if rules.blocks_everything:
        count("robots.blanket_ban_ignored", host=host)
        return True

    count("robots.disallowed", host=host, kind="feed")
    return False


async def crawl_delays(hosts: Iterable[str]) -> Mapping[str, float]:
    """Every stored crawl-delay among these hosts. One query for the whole batch."""
    wanted = {host for host in hosts if host}
    return await _stored_delays(wanted) if wanted else {}


@db.transactional
async def _stored_expiries(session: AsyncSession, hosts: set[str]) -> dict[str, datetime.datetime]:
    rows = await session.execute(
        select(Host.name, RobotsPolicy.expires_at)
        .join(RobotsPolicy, RobotsPolicy.host_id == Host.id)
        .where(Host.name.in_(hosts))
    )
    return dict(rows.all())


async def stale_hosts(known: Iterable[str], limit: int) -> list[str]:
    """Hosts needing a refresh: never asked, or past their expiry.

    Driven by the hosts we poll, so dropping a subscription stops the asking without
    anything deleting a row.
    """
    candidates = {host for host in known if host}
    if not candidates:
        return []

    stored = await _stored_expiries(candidates)
    now = datetime.datetime.now(datetime.UTC)
    stale = [host for host in candidates if host not in stored or stored[host] <= now]
    # Sorted so a batch-limited sweep is deterministic rather than set-ordered.
    return sorted(stale)[:limit]
