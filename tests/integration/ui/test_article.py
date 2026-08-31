"""One article, and what opening it records."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, ui
from old_news.db import ExtractionSource, ItemVersion, PageCapture, PageExtraction
from old_news.politeness import ensure

from factories import ExtractionFields, PageCaptureFields

LONGER = "The page reading, which runs on and is the fuller of the two."


async def test_an_article_carries_the_text_and_the_outlet(clean: None, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline", body=LONGER)

    found = await ui.article(item_id)

    assert found is not None
    assert (found.title, found.feed_body, found.outlet) == (
        "A headline",
        LONGER,
        "outlet.example.com",
    )


async def test_an_article_from_a_dropped_subscription_still_opens(clean: None, feed, story):
    """Unsubscribing takes a feed out of the river, not out of the archive."""
    item_id = await story(await feed("gone.example.com", active=False), "Still readable")

    assert (await ui.article(item_id)) is not None


async def test_nothing_is_returned_for_an_item_that_is_not_there(clean: None):
    assert await ui.article(uuid.uuid4()) is None


async def test_opening_records_the_time_once(clean: None, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline")

    first = await ui.mark_opened(item_id)
    again = await ui.mark_opened(item_id)

    assert isinstance(first, datetime.datetime)
    assert again == first
    found = await ui.article(item_id)
    assert found is not None and found.read


async def test_opening_something_that_is_not_there_says_so(clean: None):
    assert await ui.mark_opened(uuid.uuid4()) is None


async def test_an_article_knows_how_many_versions_are_held(clean: None, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline")

    found = await ui.article(item_id)

    assert found is not None and found.versions == 1


async def test_the_kicker_is_the_feeds_own_category(clean: None, feed, story):
    """A row cannot carry one; one article has exactly one feed, so it can."""
    filed = await ui.article(
        await story(await feed("tech.example.com", category="Technology"), "Filed")
    )
    loose = await ui.article(await story(await feed("loose.example.com"), "Unfiled"))

    assert filed is not None and filed.section == "Technology"
    assert loose is not None and loose.section == ""


@db.transactional
async def _page_reading(session: AsyncSession, item_id: uuid.UUID, body: str) -> None:
    """A fuller reading of the page behind the teaser, which is what makes a standfirst."""
    version = (
        await session.execute(select(ItemVersion).where(ItemVersion.item_id == item_id))
    ).scalar_one()
    capture = PageCapture(
        item_version_id=version.id,
        host_id=await ensure(session, "outlet.example.com"),
        url=version.url,
        body=b"stored",
        **PageCaptureFields.kwargs(),
    )
    session.add(capture)
    await session.flush()
    session.add(
        PageExtraction(
            item_version_id=version.id,
            page_capture_id=capture.id,
            **ExtractionFields.kwargs(source=ExtractionSource.PAGE, body=body),
        )
    )


SUMMARY = "Eleven employees, no website, and traces resold by the postcode."
OPENING = "The portal asks for a postcode and a date range, and then a purchase order."


async def test_a_feed_summary_becomes_the_standfirst_once_the_page_gives_the_article(
    clean: None, feed, story
):
    item_id = await story(await feed("outlet.example.com"), "A headline", body=SUMMARY)
    await _page_reading(item_id, f"{OPENING} There is no sign-up flow and no pricing page.")

    found = await ui.article(item_id)

    assert found is not None
    assert found.deck == SUMMARY
    assert found.page_body.startswith(OPENING)


async def test_a_teaser_the_article_simply_opens_with_is_not_a_standfirst(clean: None, feed, story):
    """A publisher syndicating full text gives a teaser that is the first paragraph, and
    repeating that above the first paragraph is worse than having none."""
    item_id = await story(await feed("outlet.example.com"), "A headline", body=OPENING)
    await _page_reading(item_id, f"{OPENING} There is no sign-up flow and no pricing page.")

    found = await ui.article(item_id)

    assert found is not None and found.deck == ""


async def test_where_the_feed_is_the_whole_article_there_is_no_standfirst(clean: None, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline", body="All of it, here.")

    found = await ui.article(item_id)

    assert found is not None and found.deck == ""


async def test_both_readings_are_held_and_the_fuller_one_opens(clean: None, feed, story):
    whole = f"{OPENING} {LONGER}"
    item_id = await story(await feed("outlet.example.com"), "A headline", body=SUMMARY)
    await _page_reading(item_id, whole)

    found = await ui.article(item_id)

    assert found is not None
    assert (found.feed_body, found.page_body, found.reading) == (SUMMARY, whole, "page")


async def test_the_feed_opens_where_it_carries_more_than_the_page_gave(clean: None, feed, story):
    """Length picks what opens, so a stub of a page reading does not take the screen."""
    item_id = await story(await feed("outlet.example.com"), "A headline", body=LONGER)
    await _page_reading(item_id, "A stub.")

    found = await ui.article(item_id)

    assert found is not None
    assert (found.feed_body, found.page_body, found.reading) == (LONGER, "A stub.", "feed")


async def test_a_reading_nobody_holds_is_empty_rather_than_absent(clean: None, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline", body=LONGER)

    found = await ui.article(item_id)

    assert found is not None and found.page_body == ""
