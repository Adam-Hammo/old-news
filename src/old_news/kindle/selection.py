"""Which articles an issue is made of, as clauses the river can borrow for its marker."""

import dataclasses
import datetime
import uuid

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, training
from old_news.config import KindleSettings
from old_news.db import (
    Extraction,
    Feed,
    IssueItem,
    Item,
    ItemVersion,
    Subscription,
    Tier,
)


@dataclasses.dataclass(frozen=True, slots=True)
class Candidate:
    """One article as an issue needs it: enough to set a page, and where to file it."""

    item_id: uuid.UUID
    title: str
    url: str
    outlet: str
    author: str
    published_at: datetime.datetime | None
    body: str


def sent() -> ColumnElement[bool]:
    """Whether this item has been in an issue. The ledger, and the only reason not to resend."""
    return exists(select(IssueItem.id).where(IssueItem.item_id == Item.id))


def has_reading() -> ColumnElement[bool]:
    """Whether anything was extracted for this item — a page with no text is a blank one."""
    return exists(
        select(Extraction.id)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
        .where(ItemVersion.item_id == Item.id, Extraction.char_count > 0)
    )


def wanted(cutoff: datetime.datetime) -> ColumnElement[bool]:
    """Everything an issue asks of a row except that it has not already gone out."""
    return and_(
        Subscription.active.is_(True),
        Subscription.tier == Tier.KINDLE,
        Item.finished_at.is_(None),
        Item.first_seen_at >= cutoff,
        ~training.blocked(ItemVersion, Item),
        has_reading(),
    )


def queued(cutoff: datetime.datetime) -> ColumnElement[bool]:
    """Whether this row would be in the next issue. Derived, so there is no queue to drift."""
    return and_(wanted(cutoff), ~sent())


def cutoff_from(
    settings: KindleSettings, now: datetime.datetime | None = None
) -> datetime.datetime:
    """How far back an issue reaches."""
    at = now or datetime.datetime.now(datetime.UTC)
    return at - datetime.timedelta(days=settings.window_days)


@db.transactional
async def candidates(session: AsyncSession, cutoff: datetime.datetime) -> tuple[Candidate, ...]:
    """The next issue's contents, grouped so one outlet's pieces sit together."""
    rows = await session.execute(
        select(
            Item.id.label("item_id"),
            ItemVersion.title.label("title"),
            func.coalesce(func.nullif(ItemVersion.canonical_url, ""), ItemVersion.url).label("url"),
            Feed.title.label("outlet"),
            ItemVersion.author.label("author"),
            ItemVersion.published_at.label("published_at"),
            Item.reading_body.label("body"),
        )
        .select_from(Item)
        .join(Item.current_version)
        .join(Feed, Feed.id == Item.feed_id)
        .join(Subscription, Subscription.feed_id == Feed.id)
        .where(queued(cutoff))
        .order_by(Feed.title, Item.first_seen_at, Item.id)
    )
    return tuple(Candidate(**row) for row in rows.mappings().all())
