"""What an issue is made of, what the ledger stops, and what the converter is handed."""

import datetime
import io
import json
import shutil
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, kindle, ui
from old_news.config import KindleSettings
from old_news.db import (
    Dimension,
    Extraction,
    ExtractionImage,
    ImageCapture,
    ImageRole,
    Issue,
    IssueItem,
    ItemVersion,
    RuleSource,
    Tier,
    TrainingRule,
)
from old_news.kindle import book, images, selection, service
from old_news.politeness import ensure

NOW = datetime.datetime.now(datetime.UTC)
DAY = datetime.timedelta(days=1)

KINDLE = KindleSettings()

# The one step that needs calibre. Everything above it is exercised without.
converter = pytest.mark.skipif(
    shutil.which(KINDLE.converter) is None, reason="calibre is not installed"
)


async def _due(settings: KindleSettings = KINDLE) -> list[str]:
    found = await selection.candidates(selection.cutoff_from(settings))
    return [candidate.title for candidate in found]


@db.transactional
async def _picture(session: AsyncSession, item_id: uuid.UUID, url: str, role: str) -> None:
    """A held image behind one article, drawn rather than fetched."""
    buffer = io.BytesIO()
    Image.new("RGB", (900, 600), (200, 40, 40)).save(buffer, "PNG")
    body = buffer.getvalue()

    capture = ImageCapture(
        url=url,
        url_digest=uuid.uuid4().bytes,
        host_id=await ensure(session, "cdn.example.com"),
        status=200,
        content_type="image/png",
        body_hash=uuid.uuid4().bytes,
        body=body,
        byte_size=len(body),
    )
    session.add(capture)
    extraction_id = await session.scalar(
        select(Extraction.id)
        .join(ItemVersion, ItemVersion.id == Extraction.item_version_id)
        .where(ItemVersion.item_id == item_id)
    )
    await session.flush()
    session.add(
        ExtractionImage(
            extraction_id=extraction_id, url=url, image_capture_id=capture.id, role=role
        )
    )


@db.transactional
async def _block(session, phrase: str) -> None:
    session.add(
        TrainingRule(
            dimension=Dimension.TITLE_PHRASE,
            pattern=phrase,
            blocks=True,
            source=RuleSource.HAND,
        )
    )


async def test_only_a_flagged_subscription_is_drawn_on(clean: None, feed, story):
    flagged = await feed("essays.example.com", tier=Tier.KINDLE)
    plain = await feed("wire.example.com")
    await story(flagged, "An essay", body="Some text.")
    await story(plain, "A dispatch", body="Some text.")

    assert await _due() == ["An essay"]


async def test_an_inactive_subscription_is_not_drawn_on(clean: None, feed, story):
    dropped = await feed("essays.example.com", tier=Tier.KINDLE, active=False)
    await story(dropped, "An essay", body="Some text.")

    assert await _due() == []


async def test_a_blocked_title_is_left_out(clean: None, feed, story):
    """The roundups and live blogs are title rules, which is how the list gets tuned."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "The Zap: this week in health", body="Some text.")
    await story(feed_id, "A real essay", body="Some text.")
    await _block("the zap:")

    assert await _due() == ["A real essay"]


async def test_something_read_to_the_bottom_is_left_out(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    read = await story(feed_id, "Already read", body="Some text.")
    await story(feed_id, "Not yet", body="Some text.")

    await ui.mark_finished(read)

    assert await _due() == ["Not yet"]


async def test_nothing_extracted_yet_is_left_out(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "A stub")

    assert await _due() == []


async def test_the_window_is_how_far_back_an_issue_reaches(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "This week", body="Some text.", first_seen_at=NOW - DAY)
    await story(feed_id, "Last month", body="Some text.", first_seen_at=NOW - 30 * DAY)

    assert await _due() == ["This week"]


async def test_an_issue_groups_one_outlets_pieces_together(clean: None, feed, story):
    first = await feed("aaa.example.com", tier=Tier.KINDLE)
    second = await feed("bbb.example.com", tier=Tier.KINDLE)
    await story(first, "A one", body="Some text.")
    await story(second, "B one", body="Some text.")
    await story(first, "A two", body="Some text.")

    assert await _due() == ["A one", "A two", "B one"]


# --- what the converter is handed ---


async def _manifest(work: Path, settings: KindleSettings = KINDLE) -> dict:
    """The layout as the recipe reads it. `work` outlives the call, so a test can look in it."""
    candidates = await selection.candidates(selection.cutoff_from(settings))
    found = await images.pictures([candidate.item_id for candidate in candidates])
    layout = book.lay_out(work, candidates, found, settings, NOW)
    return json.loads(layout.manifest.read_text())


def _written(path: str) -> str:
    return Path(path).read_text()


async def test_the_manifest_describes_one_section_per_outlet(clean: None, feed, story, tmp_path):
    first = await feed("aaa.example.com", tier=Tier.KINDLE)
    second = await feed("bbb.example.com", tier=Tier.KINDLE)
    await story(first, "A one", body="Some text.")
    await story(second, "B one", body="Some text.")

    manifest = await _manifest(tmp_path)

    assert [section["title"] for section in manifest["sections"]] == [
        "aaa.example.com",
        "bbb.example.com",
    ]


async def test_the_cover_carries_the_date_and_the_tally(clean: None, feed, story, tmp_path):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.")

    manifest = await _manifest(tmp_path)
    drawn = _written(manifest["cover"])

    assert KINDLE.title.split()[0].upper() in drawn
    assert NOW.strftime(book.DATELINE) in drawn
    assert "1 articles" in drawn


async def test_every_article_is_a_file_the_converter_can_read(clean: None, feed, story, tmp_path):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.")

    manifest = await _manifest(tmp_path)

    assert "Some text." in _written(manifest["sections"][0]["articles"][0]["file"])


async def test_the_headline_is_not_set_twice_on_a_page(clean: None, feed, story, tmp_path):
    """The extractor keeps the article's own headline, and the page adds one of its own."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "A quiet street", body="# A quiet street\n\nThe residents say.\n")

    manifest = await _manifest(tmp_path)
    page = _written(manifest["sections"][0]["articles"][0]["file"])

    assert page.count("A quiet street</h1>") == 1


# --- the ledger ---


@db.transactional
async def _ledger(session) -> list[tuple[str, int]]:
    rows = await session.execute(
        select(IssueItem.section, IssueItem.position).order_by(IssueItem.position)
    )
    return [(row.section, row.position) for row in rows]


@converter
async def test_a_built_issue_records_what_it_carried(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.")

    built = await service.build_issue(KINDLE, NOW)

    assert built.articles == 1
    assert built.byte_size > 0
    assert await _ledger() == [("essays.example.com", 1)]


@converter
async def test_an_article_already_sent_is_not_sent_again(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.")
    await service.build_issue(KINDLE, NOW)

    again = await service.build_issue(KINDLE, NOW)

    assert again.issue_id is None
    assert again.articles == 0


@converter
async def test_a_quiet_week_builds_nothing_rather_than_an_empty_book(clean: None, feed, story):
    """An email saying there is nothing to read is worse than silence."""
    await feed("essays.example.com", tier=Tier.KINDLE)

    built = await service.build_issue(KINDLE, NOW)

    assert built == kindle.Built(None, 0, 0, False, "")


@converter
async def test_an_issue_keeps_the_bytes_it_sent(clean: None, feed, story):
    """E999 carries no detail, so posting the identical book again is the only diagnosis."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.")

    await service.build_issue(KINDLE, NOW)

    async with db.session() as session:
        issue = (await session.execute(select(Issue))).scalar_one()
        assert issue.body[:2] == b"PK"
        assert issue.byte_size == len(issue.body)
        assert issue.sent_at is None
        assert issue.error == ""


@converter
async def test_the_images_an_article_referred_to_reach_the_book(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    item_id = await story(
        feed_id, "An essay", body="Text.\n\n![a chart](https://cdn.example.com/a.png)\n"
    )
    await _picture(item_id, "https://cdn.example.com/a.png", ImageRole.BODY)

    built = await service.build_issue(KINDLE, NOW)

    assert built.articles == 1
    async with db.session() as session:
        issue = (await session.execute(select(Issue))).scalar_one()
    # A JPEG of the drawn chart is in there, so the book is bigger than its text.
    assert issue.byte_size > 20_000
