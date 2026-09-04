"""The contents page, and the shelves off it. Every list here has an end."""

import datetime
import uuid

import pytest

from old_news import ui
from old_news.config import KindleSettings
from old_news.db import Tier

NOW = datetime.datetime.now(datetime.UTC)
DAY = datetime.timedelta(days=1)

KINDLE = KindleSettings()

SYDNEY = "Australia/Sydney"


async def _titles(**kwargs) -> list[str]:
    return [entry.title for entry in (await ui.shelf(KINDLE, **kwargs)).entries]


async def test_the_contents_counts_what_the_archive_holds(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=DAY)
    await story(feed_id, "Today")
    await story(feed_id, "Last year", first_seen_at=NOW - 365 * DAY)

    assert (await ui.contents()).items == 2


async def test_a_publication_is_one_shelf(clean: None, feed, story):
    kept = await feed("essays.example.com")
    other = await feed("wire.example.com")
    await story(kept, "An essay")
    await story(other, "A bulletin")

    assert await _titles(feed=kept) == ["An essay"]


async def test_a_dropped_feeds_run_is_still_held(clean: None, feed, story):
    """Unfollowing stops the polling. The archive is the database, so it keeps the rows."""
    feed_id = await feed("gone.example.com", active=False)
    await story(feed_id, "From before")

    run = next(row for row in (await ui.contents()).feeds if row.feed_id == feed_id)

    assert (run.dropped, run.items) == (True, 1)
    assert await _titles(feed=feed_id) == ["From before"]


async def test_a_run_carries_the_tier_it_is_filed_at(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay")

    assert (await ui.contents()).feeds[0].tier == Tier.KINDLE


async def test_a_month_is_one_shelf(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "In June", first_seen_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "In July", first_seen_at=datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
    )

    assert await _titles(month="2026-06") == ["In June"]


async def test_the_months_shelf_lists_what_is_in_each(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "In June", first_seen_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "In July", first_seen_at=datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
    )

    months = (await ui.contents()).months

    assert [(volume.month, volume.items) for volume in months] == [("2026-07", 1), ("2026-06", 1)]


async def test_a_month_is_grouped_in_the_readers_own_zone(clean: None, feed, story):
    """22.00 UTC on the 31st is already the 1st in Sydney, and the shelf has to say so."""
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "Late July", first_seen_at=datetime.datetime(2026, 7, 31, 22, tzinfo=datetime.UTC)
    )

    assert (await ui.contents(zone=SYDNEY)).months[0].month == "2026-08"
    assert await _titles(month="2026-08", zone=SYDNEY) == ["Late July"]
    assert await _titles(month="2026-07", zone=SYDNEY) == []


async def test_december_rolls_into_the_next_year(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "Christmas", first_seen_at=datetime.datetime(2025, 12, 25, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "New year", first_seen_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    )

    assert await _titles(month="2025-12") == ["Christmas"]


async def test_a_shelf_can_be_a_publication_within_a_month(clean: None, feed, story):
    essays = await feed("essays.example.com")
    wire = await feed("wire.example.com")
    june = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    await story(essays, "An essay in June", first_seen_at=june)
    await story(wire, "A bulletin in June", first_seen_at=june)

    assert await _titles(feed=essays, month="2026-06") == ["An essay in June"]


async def test_the_wire_can_be_left_off_a_month(clean: None, feed, story):
    """The one filter a month needs: the wire is most of the archive and none of the point."""
    wire = await feed("wire.example.com", tier=Tier.WIRE)
    kept = await feed("essays.example.com", tier=Tier.ARCHIVE)
    await story(wire, "A bulletin")
    await story(kept, "An essay")

    assert sorted(await _titles(month=NOW.strftime("%Y-%m"), tier=Tier.ARCHIVE)) == ["An essay"]


async def test_a_shelf_pages_to_its_end(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    for day in range(5):
        await story(feed_id, f"Day {day}", first_seen_at=NOW - day * DAY)

    seen: list[str] = []
    cursor = ""
    while True:
        page = await ui.shelf(KINDLE, feed=feed_id, after=cursor, limit=2)
        seen += [entry.title for entry in page.entries]
        if not page.cursor:
            break
        cursor = page.cursor

    assert seen == ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4"]


async def test_what_has_aged_out_of_the_river_is_on_its_shelf(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=2 * DAY)
    await story(feed_id, "Last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles(feed=feed_id) == ["Last week"]
    assert [entry.title for entry in (await ui.river(KINDLE)).entries] == []


async def test_a_shelf_of_everything_is_refused(clean: None):
    """The whole archive as one list is what this screen exists to replace."""
    with pytest.raises(ui.BadShelf):
        await ui.shelf(KINDLE)


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"month": "2026-13"}, id="no-thirteenth-month"),
        pytest.param({"month": "June"}, id="not-a-month-at-all"),
        pytest.param({"month": "2026-06", "zone": "Mars/Olympus"}, id="no-such-zone"),
        pytest.param({"feed": uuid.UUID(int=1), "tier": "gold"}, id="no-such-tier"),
    ],
)
async def test_an_impossible_shelf_is_refused(clean: None, kwargs):
    with pytest.raises(ui.BadShelf):
        await ui.shelf(KINDLE, **kwargs)


async def test_an_unusable_zone_is_refused_by_the_contents(clean: None):
    with pytest.raises(ui.BadShelf):
        await ui.contents(zone="Mars/Olympus")
