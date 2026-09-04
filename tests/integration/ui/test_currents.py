"""What ages out of the river, what the archive still holds, and what a row is marked with."""

import datetime

from old_news import ui
from old_news.config import KindleSettings
from old_news.db import Tier

NOW = datetime.datetime.now(datetime.UTC)
DAY = datetime.timedelta(days=1)

KINDLE = KindleSettings()


async def _titles(**kwargs) -> list[str]:
    return [entry.title for entry in (await ui.river(KINDLE, **kwargs)).entries]


async def test_a_feed_with_no_window_never_ages_out(clean: None, feed, story):
    """Null is what every row starts as, so nothing disappears until a window is set."""
    feed_id = await feed("kept.example.com")
    await story(feed_id, "From last year", first_seen_at=NOW - 365 * DAY)

    assert await _titles() == ["From last year"]


async def test_an_item_older_than_its_window_leaves_the_river(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=2 * DAY)
    await story(feed_id, "Today", first_seen_at=NOW - DAY)
    await story(feed_id, "Last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles() == ["Today"]


async def test_the_archive_is_the_same_river_with_the_cutoff_lifted(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=2 * DAY)
    await story(feed_id, "Today", first_seen_at=NOW - DAY)
    await story(feed_id, "Last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles(archive=True) == ["Today", "Last week"]


async def test_each_feed_ages_out_on_its_own_window(clean: None, feed, story):
    """The point of hanging it off the subscription rather than the section."""
    fast = await feed("wire.example.com", category="Wire", expires_after=2 * DAY)
    slow = await feed("essays.example.com", category="Wire", expires_after=60 * DAY)
    await story(fast, "Wire, last week", first_seen_at=NOW - 7 * DAY)
    await story(slow, "Essay, last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles(section="Wire") == ["Essay, last week"]


async def test_expiry_survives_a_page_boundary(clean: None, feed, story):
    """The cutoff and the cursor are bounds on the same key, so paging cannot leak a row."""
    # Half a day of margin, or the row sitting exactly on the cutoff races the clock.
    feed_id = await feed("wire.example.com", expires_after=3 * DAY + datetime.timedelta(hours=12))
    for day in range(6):
        await story(feed_id, f"Day {day}", first_seen_at=NOW - day * DAY)

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
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE, expires_after=365 * DAY)
    await story(feed_id, "An old essay", body="Some text.", first_seen_at=NOW - 30 * DAY)

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
