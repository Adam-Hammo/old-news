"""Which pages are worth fetching, as one query.

The rule lives here whole rather than spread over a call chain, so it reads in one go and
can be tested case by case. Modelled on `ingest.service.due_polls`, which is the same
shape: claim a batch, group it by host, hand it to the queue.
"""

import dataclasses
import datetime
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, training
from old_news.config import ExtractSettings
from old_news.db import (
    CAPTURE_POLICY,
    CaptureOutcome,
    Host,
    Item,
    ItemVersion,
    PageCapture,
    RobotsPolicy,
)
from old_news.extract import breaker
from old_news.politeness import backoff, host_of


@dataclasses.dataclass(frozen=True, slots=True)
class DueCapture:
    """A page to fetch, and the host politeness groups it under."""

    version_id: uuid.UUID
    url: str
    host: str


@db.transactional
async def due_captures(
    session: AsyncSession, settings: ExtractSettings, limit: int
) -> list[DueCapture]:
    """Head versions whose page we should have and do not.

    The first version of an item is due at once, so every article has something; a later
    one waits for the settle window, so a rolling story does not cost a fetch per rewrite.
    The version cap and the blocking rule are what make a live blog cost nothing.
    """
    now = datetime.datetime.now(datetime.UTC)
    settled_by = now - datetime.timedelta(seconds=settings.settle_seconds)
    policy = backoff.policy_for(settings.capture_retry)

    captured = select(PageCapture.item_version_id).where(PageCapture.succeeded).scalar_subquery()

    # Every visit records which host it went to, so the answers to "have we been told no
    # here" are all in one table and none of them has to be re-derived from a URL.
    #
    # A version we have already visited on a host that is shut is not asked again, and
    # neither is one robots forbade. Both are excluded in SQL rather than after the
    # `LIMIT`, because dropping rows from a claimed batch silently shrinks it — the
    # version stays due, leads the batch by age, and takes the same slot every minute.
    # Twenty-five of those captured nothing for three hours.
    #
    # A version never visited at all is not covered here, and does not need to be: the
    # first sweep that picks it up records the refusal, and from then on it is.
    on_refusing = (
        select(PageCapture.item_version_id)
        .where(
            PageCapture.host_id.in_(select(Host.id).where(breaker.refusing(Host, settings, now)))
        )
        .scalar_subquery()
    )

    # Robots is a cache, so a refusal only holds until the rules are read again. Re-read
    # them and every page they forbade is a candidate once more, which is what makes
    # this a delay rather than a verdict.
    forbidden = (
        select(PageCapture.item_version_id)
        .join(RobotsPolicy, RobotsPolicy.host_id == PageCapture.host_id)
        .where(
            PageCapture.outcome == CaptureOutcome.DISALLOWED,
            PageCapture.fetched_at > RobotsPolicy.fetched_at,
        )
        .scalar_subquery()
    )

    unread = (
        select(PageCapture.item_version_id)
        .outerjoin(RobotsPolicy, RobotsPolicy.host_id == PageCapture.host_id)
        .where(
            PageCapture.outcome == CaptureOutcome.UNKNOWN_RULES,
            RobotsPolicy.id.is_(None),
        )
        .scalar_subquery()
    )

    # Only the visits that were actually sent and actually refused. A row saying we
    # declined to ask must not spend one of the tries a page gets, or a host being shut
    # for an afternoon would write off every article on it.
    tried = (
        select(
            PageCapture.item_version_id.label("version_id"),
            func.count().label("failures"),
            func.max(PageCapture.fetched_at).label("last_attempt"),
        )
        .where(
            PageCapture.capture_policy == CAPTURE_POLICY,
            PageCapture.outcome == CaptureOutcome.FAILED,
        )
        .group_by(PageCapture.item_version_id)
        .subquery()
    )

    rows = await session.execute(
        select(ItemVersion.id, ItemVersion.url, ItemVersion.canonical_url)
        .join(Item, Item.id == ItemVersion.item_id)
        .outerjoin(tried, tried.c.version_id == ItemVersion.id)
        .where(
            Item.subscribed,
            ItemVersion.is_head,
            ItemVersion.id.not_in(captured),
            ItemVersion.id.not_in(on_refusing),
            ItemVersion.id.not_in(forbidden),
            ItemVersion.id.not_in(unread),
            Item.version_count <= settings.max_versions_per_item,
            ~training.blocked(ItemVersion, Item),
            # A version superseding nothing is the item's first, and is due at once.
            ItemVersion.supersedes_id.is_(None) | (ItemVersion.observed_at <= settled_by),
            # Never tried, or refused and now off its backoff with tries still left.
            # Without this a page that will never answer is asked once a minute forever.
            or_(
                tried.c.version_id.is_(None),
                and_(
                    tried.c.failures < policy.max_failures,
                    backoff.due_at(tried.c.last_attempt, tried.c.failures, policy) <= now,
                ),
            ),
        )
        .order_by(ItemVersion.observed_at)
        .limit(limit)
    )

    known = await _hosts_with_rules(session)
    due = []
    for version_id, url, canonical_url in rows:
        target = canonical_url or url
        host = host_of(target)
        # A link that is not fetchable at all — an aggregator naming a `newsletter:`
        # address, say — has no page to get. And a host whose robots.txt has never been
        # read is left alone: unknown rules read as permission everywhere else in the
        # codebase, which is right for a feed published for readers and wrong for
        # crawling a publisher's pages. The refresh sweep writes a row for every host it
        # visits, reachable or not, so this delays a new host rather than blocking it.
        if host and host in known:
            due.append(DueCapture(version_id, target, host))
    return due


async def _hosts_with_rules(session: AsyncSession) -> set[str]:
    """Hosts whose robots.txt has been asked for, whatever it said."""
    rows = await session.execute(
        select(Host.name).join(RobotsPolicy, RobotsPolicy.host_id == Host.id)
    )
    return set(rows.scalars().all())


@db.transactional
async def article_hosts(session: AsyncSession) -> list[str]:
    """Every host we fetch articles from, which is not the set we poll.

    BBC's feed is on `feeds.bbci.co.uk` and its articles are on `bbc.co.uk`. Without this
    the robots refresh never asks the host being crawled, and the rules lookup, finding
    nothing stored, allows everything.
    """
    rows = await session.execute(
        select(ItemVersion.url, ItemVersion.canonical_url)
        .join(Item, Item.id == ItemVersion.item_id)
        .where(Item.subscribed)
        .distinct()
    )
    hosts = {host_of(canonical or url) for url, canonical in rows}
    return sorted(hosts - {""})
