"""Which pages are worth fetching, as one query."""

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
    """Head versions whose page we should have and do not."""
    now = datetime.datetime.now(datetime.UTC)
    settled_by = now - datetime.timedelta(seconds=settings.settle_seconds)
    policy = backoff.policy_for(settings.capture_retry)

    # Excluded in SQL, not after the `LIMIT`: dropping rows from a claimed batch shrinks
    # it, and the version stays due and leads the next one by age. A version never
    # visited is not covered and needs no covering — the first sweep to reach it records
    # the refusal, and from then on it is.
    settled = (
        select(PageCapture.item_version_id)
        .outerjoin(RobotsPolicy, RobotsPolicy.host_id == PageCapture.host_id)
        .where(
            or_(
                PageCapture.succeeded,
                PageCapture.host_id.in_(
                    select(Host.id).where(breaker.refusing(Host, settings, now))
                ),
                # A cache, so its refusal holds only until the rules are read again.
                and_(
                    PageCapture.outcome == CaptureOutcome.DISALLOWED,
                    PageCapture.fetched_at > RobotsPolicy.fetched_at,
                ),
                and_(
                    PageCapture.outcome == CaptureOutcome.UNKNOWN_RULES,
                    RobotsPolicy.id.is_(None),
                ),
            )
        )
        .scalar_subquery()
    )

    # Only visits actually sent. A decline must not spend one of a page's limited tries.
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
            ItemVersion.id.not_in(settled),
            Item.version_count <= settings.max_versions_per_item,
            ~training.blocked(ItemVersion, Item),
            # A version superseding nothing is the item's first, and is due at once.
            ItemVersion.supersedes_id.is_(None) | (ItemVersion.observed_at <= settled_by),
            # Never tried, or refused and now off its backoff with tries still left.
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
        # A host whose robots.txt has never been read is left for the refresh sweep, which
        # writes a row whether or not it could reach one — so this delays, not blocks.
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
    """Every host we fetch articles from, which is not the set we poll."""
    rows = await session.execute(
        select(ItemVersion.url, ItemVersion.canonical_url)
        .join(Item, Item.id == ItemVersion.item_id)
        .where(Item.subscribed)
        .distinct()
    )
    hosts = {host_of(canonical or url) for url, canonical in rows}
    return sorted(hosts - {""})
