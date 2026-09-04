"""Building one issue: select, set, convert, record, post. Each step its own transaction."""

import asyncio
import dataclasses
import datetime
import logging
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.config import KindleSettings
from old_news.db import Issue, IssueItem
from old_news.kindle import book, convert, deliver, images, selection
from old_news.observability import count, span

logger = logging.getLogger(__name__)

BOOK = "issue.epub"


@dataclasses.dataclass(frozen=True, slots=True)
class Built:
    """What came out of a build. No articles is an ordinary quiet week, not a failure."""

    issue_id: uuid.UUID | None
    articles: int
    byte_size: int
    sent: bool
    error: str


@db.transactional
async def _record(
    session: AsyncSession,
    *,
    title: str,
    subject: str,
    body: bytes,
    placed: Sequence[book.Placed],
) -> uuid.UUID:
    """The issue and its contents in one write, so nothing is ever half-recorded."""
    issue = Issue(title=title, subject=subject, body=body, byte_size=len(body))
    session.add(issue)
    await session.flush()
    session.add_all(
        IssueItem(
            issue_id=issue.id,
            item_id=article.item_id,
            section=article.section,
            position=article.position,
        )
        for article in placed
    )
    return issue.id


@db.transactional
async def _stored(
    session: AsyncSession, issue_id: uuid.UUID
) -> tuple[bytes, str, datetime.datetime] | None:
    """An issue's bytes as they went out, for posting the identical book again."""
    row = (
        await session.execute(
            select(Issue.body, Issue.subject, Issue.built_at).where(Issue.id == issue_id)
        )
    ).first()
    return None if row is None else (row.body, row.subject, row.built_at)


@db.transactional
async def _posted(
    session: AsyncSession, issue_id: uuid.UUID, error: str, at: datetime.datetime
) -> None:
    """Stamp the outcome. An error leaves `sent_at` null, so a resend can find it."""
    await session.execute(
        update(Issue).where(Issue.id == issue_id).values(error=error, sent_at=None if error else at)
    )


async def _lay_out(
    work: Path, settings: KindleSettings, at: datetime.datetime
) -> book.Layout | None:
    """Everything due, set as pages. None where the week was quiet."""
    due = await selection.candidates(selection.cutoff_from(settings, at))
    candidates = tuple(found for found in due if found.body)
    if not candidates:
        return None
    pictures = await images.pictures([found.item_id for found in candidates])
    # Hundreds of images re-encoded, so off the loop the worker is serving on.
    return await asyncio.to_thread(book.lay_out, work, candidates, pictures, settings, at)


async def _post(
    issue_id: uuid.UUID,
    layout: book.Layout,
    body: bytes,
    settings: KindleSettings,
    at: datetime.datetime,
) -> str:
    """Send it, and record whether it went. The error text, or empty."""
    error = ""
    try:
        await deliver.send(body, subject=layout.subject, at=at, settings=settings)
    except deliver.NotDelivered as exc:
        error = str(exc)
        logger.warning("issue %s did not go out: %s", issue_id, error)
    await _posted(issue_id, error, at)
    count("kindle.issues.failed" if error else "kindle.issues.sent")
    return error


async def build_issue(settings: KindleSettings, at: datetime.datetime | None = None) -> Built:
    """One periodical from whatever is due. Silent on a quiet week rather than empty."""
    at = at or datetime.datetime.now(datetime.UTC)

    with span("build kindle issue") as current:
        with tempfile.TemporaryDirectory(prefix="old-news-issue-") as scratch:
            work = Path(scratch)
            layout = await _lay_out(work, settings, at)
            if layout is None:
                logger.info("nothing due for the kindle; no issue built")
                count("kindle.issues.empty")
                return Built(None, 0, 0, False, "")

            body = await convert.to_epub(layout.manifest, work / BOOK, settings)

        issue_id = await _record(
            title=layout.title, subject=layout.subject, body=body, placed=layout.placed
        )
        current.set_attributes(
            {
                "issue.id": str(issue_id),
                "issue.articles": len(layout.placed),
                "issue.bytes": len(body),
            }
        )
        count("kindle.issues.built")
        count("kindle.articles.sent", len(layout.placed))

        if not settings.deliverable:
            logger.info("issue %s built; delivery is not configured", issue_id)
            return Built(issue_id, len(layout.placed), len(body), False, "")

        error = await _post(issue_id, layout, body, settings, at)
        return Built(issue_id, len(layout.placed), len(body), not error, error)


async def resend(issue_id: uuid.UUID, settings: KindleSettings) -> str:
    """Post the same bytes again — the only way to tell a bad book from a bad night."""
    stored = await _stored(issue_id)
    if stored is None:
        return "no such issue"

    body, subject, built_at = stored
    at = datetime.datetime.now(datetime.UTC)
    try:
        await deliver.send(body, subject=subject, at=built_at, settings=settings)
    except deliver.NotDelivered as exc:
        await _posted(issue_id, str(exc), at)
        return str(exc)
    await _posted(issue_id, "", at)
    return ""
