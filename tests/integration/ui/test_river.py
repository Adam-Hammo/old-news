"""What the river shows, in what order, and what it leaves out."""

import datetime
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db, ui
from old_news.db import Dimension, Feed, RuleSource, TrainingRule

NOW = datetime.datetime(2026, 8, 31, 12, 0, tzinfo=datetime.UTC)
MINUTE = datetime.timedelta(minutes=1)


async def _titles(**kwargs) -> list[str]:
    return [entry.title for entry in (await ui.river(**kwargs)).entries]


@db.transactional
async def _block(session: AsyncSession, phrase: str) -> None:
    session.add(
        TrainingRule(
            dimension=Dimension.TITLE_PHRASE,
            pattern=phrase,
            blocks=True,
            source=RuleSource.HAND,
        )
    )


async def test_the_river_sorts_on_when_we_first_saw_it_not_the_publishers_date(
    clean: None, feed, story
):
    """A backfilled 2019 article arrives at the top of nothing."""
    feed_id = await feed("outlet.example.com")
    await story(feed_id, "Old news", first_seen_at=NOW, published_at=NOW - datetime.timedelta(2000))
    await story(feed_id, "Newer", first_seen_at=NOW - MINUTE, published_at=NOW)

    assert await _titles() == ["Old news", "Newer"]


async def test_items_from_one_poll_share_a_timestamp_and_still_page_cleanly(
    clean: None, feed, story
):
    """`first_seen_at` is CURRENT_TIMESTAMP, so a whole poll ties. The id is the tiebreak."""
    feed_id = await feed("outlet.example.com")
    for index in range(5):
        await story(feed_id, f"Story {index}", first_seen_at=NOW)

    seen: list[str] = []
    cursor = ""
    while True:
        page = await ui.river(after=cursor, limit=2)
        seen.extend(entry.title for entry in page.entries)
        cursor = page.cursor
        if not cursor:
            break

    assert sorted(seen) == [f"Story {index}" for index in range(5)]
    assert len(seen) == len(set(seen))


async def test_the_last_page_ends_the_cursor(clean: None, feed, story):
    feed_id = await feed("outlet.example.com")
    await story(feed_id, "Only one")

    assert (await ui.river(limit=2)).cursor == ""


async def test_a_section_shows_only_the_feeds_filed_under_it(clean: None, feed, story):
    technology = await feed("tech.example.com", category="Technology")
    science = await feed("science.example.com", category="Science")
    await story(technology, "A chip")
    await story(science, "A telescope")

    assert await _titles(section="Technology") == ["A chip"]
    assert sorted(await _titles()) == ["A chip", "A telescope"]


async def test_an_unfiled_feed_is_in_the_whole_river_and_no_section(clean: None, feed, story):
    await story(await feed("loose.example.com"), "Unfiled")

    assert await _titles() == ["Unfiled"]
    assert await _titles(section="Technology") == []


async def test_a_dropped_subscription_leaves_the_river(clean: None, feed, story):
    await story(await feed("gone.example.com", active=False), "Not followed")
    await story(await feed("kept.example.com"), "Followed")

    assert await _titles() == ["Followed"]


async def test_a_blocked_item_never_shows(clean: None, feed, story):
    feed_id = await feed("outlet.example.com")
    await story(feed_id, "Politics live blog", first_seen_at=NOW)
    await story(feed_id, "A real article", first_seen_at=NOW - MINUTE)
    await _block("live blog")

    assert await _titles() == ["A real article"]


async def test_each_row_carries_its_own_deck(clean: None, feed, story):
    """One correlated subquery per row, so a lost correlation shows here and nowhere else."""
    feed_id = await feed("outlet.example.com")
    await story(feed_id, "First", body="# Alpha\n\nThe alpha body.", first_seen_at=NOW)
    await story(
        feed_id, "Second", body="The beta body, which is longer.", first_seen_at=NOW - MINUTE
    )

    decks = {entry.title: entry.deck for entry in (await ui.river()).entries}

    assert decks == {"First": "Alpha The alpha body.", "Second": "The beta body, which is longer."}


async def test_an_item_with_nothing_extracted_yet_still_shows(clean: None, feed, story):
    await story(await feed("outlet.example.com"), "Just arrived")

    entry = (await ui.river()).entries[0]

    assert (entry.title, entry.deck, entry.read) == ("Just arrived", "", False)


async def test_sections_are_the_categories_of_active_subscriptions(clean: None, feed):
    await feed("tech.example.com", category="Technology")
    await feed("science.example.com", category="Science")
    await feed("loose.example.com")
    await feed("dropped.example.com", category="Politics", active=False)

    assert await ui.sections() == ("Science", "Technology")


async def test_a_cursor_we_did_not_write_is_refused(clean: None):
    with pytest.raises(ui.BadCursor):
        await ui.river(after="nonsense!")


async def test_the_masthead_carries_the_newest_successful_poll(clean: None, feed, story):
    """Not a count of anything: the question is whether this is still working."""
    feed_id = await feed("outlet.example.com")
    await story(feed_id, "A headline")
    await _polled(feed_id, NOW)

    assert (await ui.river()).updated == NOW


@db.transactional
async def _polled(session: AsyncSession, feed_id: uuid.UUID, at: datetime.datetime) -> None:
    await session.execute(update(Feed).where(Feed.id == feed_id).values(last_success_at=at))
