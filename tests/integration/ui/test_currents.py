"""What ages out of the river, what the archive still holds, and what a row is marked with."""

import datetime

from old_news import ui
from old_news.config import KindleSettings
from old_news.db import Tier

NOW = datetime.datetime.now(datetime.UTC)
DAY = datetime.timedelta(days=1)
HOUR = datetime.timedelta(hours=1)

KINDLE = KindleSettings()


async def _titles(**kwargs) -> list[str]:
    return [entry.title for entry in (await ui.river(KINDLE, **kwargs)).entries]


async def test_a_feed_nobody_has_filed_still_ages_out(clean: None, feed, story):
    """There is no window that keeps a thing in the river: past the longest one it is archive."""
    feed_id = await feed("kept.example.com")
    await story(feed_id, "This week", first_seen_at=NOW - DAY)
    await story(feed_id, "From last year", first_seen_at=NOW - 365 * DAY)

    assert await _titles() == ["This week"]


async def test_an_item_older_than_its_window_leaves_the_river(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=2 * DAY)
    await story(feed_id, "Today", first_seen_at=NOW - DAY)
    await story(feed_id, "Last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles() == ["Today"]


async def test_each_feed_ages_out_on_its_own_window(clean: None, feed, story):
    """The point of hanging it off the subscription rather than the section."""
    fast = await feed("wire.example.com", category="Wire", expires_after=2 * DAY)
    slow = await feed("essays.example.com", category="Wire", expires_after=30 * DAY)
    await story(fast, "Wire, last week", first_seen_at=NOW - 7 * DAY)
    await story(slow, "Essay, last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles(section="Wire") == ["Essay, last week"]


async def test_expiry_survives_a_page_boundary(clean: None, feed, story):
    """The cutoff is on one key and the cursor on another, so paging has to hold them both."""
    # Half a day of margin, or the row sitting exactly on the cutoff races the clock.
    feed_id = await feed("wire.example.com", expires_after=3 * DAY + datetime.timedelta(hours=12))
    for day in range(6):
        # Two days behind the sighting, so every row is placed by the ceiling and not its date.
        await story(
            feed_id,
            f"Day {day}",
            first_seen_at=NOW - day * DAY,
            published_at=NOW - day * DAY - 2 * DAY,
        )

    seen: list[str] = []
    cursor = ""
    while True:
        page = await ui.river(KINDLE, after=cursor, limit=2)
        seen += [entry.title for entry in page.entries]
        if not page.cursor:
            break
        cursor = page.cursor

    assert seen == ["Day 0", "Day 1", "Day 2", "Day 3"]


async def test_an_unflagged_feed_marks_nothing(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(feed_id, "A story", body="Some text.", first_seen_at=NOW)

    entry = (await ui.river(KINDLE)).entries[0]

    assert (entry.sent, entry.queued) == (False, False)


async def test_a_flagged_feeds_row_is_marked_due(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Some text.", first_seen_at=NOW)

    entry = (await ui.river(KINDLE)).entries[0]

    assert (entry.sent, entry.queued) == (False, True)


async def test_nothing_extracted_yet_is_not_due(clean: None, feed, story):
    """A page with no text on it is not a page worth sending."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "A stub", first_seen_at=NOW)

    assert (await ui.river(KINDLE)).entries[0].queued is False


async def test_reading_an_article_to_the_bottom_takes_it_off_the_list(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    item_id = await story(feed_id, "An essay", body="Some text.", first_seen_at=NOW)

    await ui.mark_finished(item_id)

    assert (await ui.river(KINDLE)).entries[0].queued is False


async def test_opening_an_article_leaves_it_due(clean: None, feed, story):
    """Opened is a tap. Skimming two paragraphs is the case the Kindle is for."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    item_id = await story(feed_id, "An essay", body="Some text.", first_seen_at=NOW)

    await ui.mark_opened(item_id)

    assert (await ui.river(KINDLE)).entries[0].queued is True


async def test_an_item_past_the_kindle_window_is_not_due(clean: None, feed, story):
    """Its window is long, but a weekly issue only reaches back a week."""
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE, expires_after=30 * DAY)
    await story(feed_id, "An old essay", body="Some text.", first_seen_at=NOW - 20 * DAY)

    assert (await ui.river(KINDLE)).entries[0].queued is False


async def test_marking_finished_is_the_first_time_only(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    item_id = await story(feed_id, "An essay", body="Some text.")

    first = await ui.mark_finished(item_id)
    again = await ui.mark_finished(item_id)

    assert first == again


async def test_finishing_an_article_counts_as_opening_it(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    item_id = await story(feed_id, "An essay", body="Some text.")

    await ui.mark_finished(item_id)

    article = await ui.article(item_id)
    assert article is not None
    assert article.read is True


async def test_a_backlog_a_new_feed_arrives_with_is_not_the_river(clean: None, feed, story):
    """A first poll backfills years under one afternoon. The river takes what was new then."""
    feed_id = await feed("essays.example.com", expires_after=30 * DAY)
    await story(feed_id, "Last week", first_seen_at=NOW, published_at=NOW - 7 * DAY)
    await story(feed_id, "From 2023", first_seen_at=NOW, published_at=NOW - 900 * DAY)

    assert await _titles() == ["Last week"]


async def test_a_late_poll_does_not_shorten_the_shelf(clean: None, feed, story):
    """The bound is off when we saw it, so a late poll costs the row none of its shelf."""
    feed_id = await feed("essays.example.com", expires_after=10 * DAY)
    await story(feed_id, "Found late", first_seen_at=NOW - 9 * DAY, published_at=NOW - 18 * DAY)

    assert await _titles() == ["Found late"]


async def test_a_publisher_who_dates_nothing_still_has_a_river(clean: None, feed, story):
    """No publish date is not a stale one — xkcd and Tedium carry none at all."""
    feed_id = await feed("comics.example.com", expires_after=10 * DAY)
    await story(feed_id, "Today", first_seen_at=NOW)
    await story(feed_id, "Last month", first_seen_at=NOW - 30 * DAY)

    assert await _titles() == ["Today"]


async def test_a_short_window_still_allows_for_a_slow_poll(clean: None, feed, story):
    """A wire feed's window is shorter than backoff, and being late must not empty it."""
    feed_id = await feed("wire.example.com", expires_after=DAY)
    await story(feed_id, "Found late", first_seen_at=NOW, published_at=NOW - 30 * HOUR)

    assert await _titles() == ["Found late"]


async def test_a_piece_older_than_the_tolerance_is_archive_not_river(clean: None, feed, story):
    """The other side of the same bound: past it a row never reaches the river at all."""
    feed_id = await feed("essays.example.com", expires_after=10 * DAY)
    await story(feed_id, "Found far too late", first_seen_at=NOW, published_at=NOW - 11 * DAY)

    assert await _titles() == []
