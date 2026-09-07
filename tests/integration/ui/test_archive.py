"""The contents page, and the one query path off it."""

import datetime

import pytest

from old_news import ui
from old_news.config import KindleSettings
from old_news.db import Tier

NOW = datetime.datetime.now(datetime.UTC)
DAY = datetime.timedelta(days=1)

KINDLE = KindleSettings()

SYDNEY = "Australia/Sydney"


async def _found(typed: str = "", **kwargs) -> ui.Found:
    return await ui.held(KINDLE, asked=ui.parse(typed), **kwargs)


async def _titles(typed: str = "", **kwargs) -> list[str]:
    return [entry.title for entry in (await _found(typed, **kwargs)).listing.entries]


def _month(month: str) -> str:
    """A month as the grammar spells one: its first day, up to the next month's."""
    year, ordinal = (int(part) for part in month.split("-"))
    return f"after:{month} before:{year + ordinal // 12}-{ordinal % 12 + 1:02d}"


async def test_the_contents_counts_what_the_archive_holds(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=DAY)
    await story(feed_id, "Today")
    await story(feed_id, "Last year", first_seen_at=NOW - 365 * DAY)

    assert (await ui.contents()).items == 2


async def test_a_publication_is_named_rather_than_identified(clean: None, feed, story):
    kept = await feed("essays.example.com")
    other = await feed("wire.example.com")
    await story(kept, "An essay")
    await story(other, "A bulletin")

    assert await _titles("from:essays.example.com") == ["An essay"]


async def test_a_dropped_feeds_run_is_still_held(clean: None, feed, story):
    """Unfollowing stops the polling. The archive is the database, so it keeps the rows."""
    feed_id = await feed("gone.example.com", active=False)
    await story(feed_id, "From before")

    run = next(row for row in (await ui.contents()).feeds if row.feed_id == feed_id)

    assert (run.dropped, run.items) == (True, 1)
    assert await _titles("from:gone.example.com") == ["From before"]


async def test_a_run_carries_the_tier_it_is_filed_at(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay")

    assert (await ui.contents()).feeds[0].tier == Tier.KINDLE


async def test_a_month_is_a_pair_of_dates(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "In June", first_seen_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "In July", first_seen_at=datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
    )

    assert await _titles(_month("2026-06")) == ["In June"]


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
    assert await _titles(_month("2026-08"), zone=SYDNEY) == ["Late July"]
    assert await _titles(_month("2026-07"), zone=SYDNEY) == []


async def test_december_rolls_into_the_next_year(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "Christmas", first_seen_at=datetime.datetime(2025, 12, 25, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "New year", first_seen_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    )

    assert await _titles(_month("2025-12")) == ["Christmas"]


async def test_a_publication_and_a_month_compose(clean: None, feed, story):
    essays = await feed("essays.example.com")
    wire = await feed("wire.example.com")
    june = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    await story(essays, "An essay in June", first_seen_at=june)
    await story(wire, "A bulletin in June", first_seen_at=june)

    assert await _titles(f"from:essays.example.com {_month('2026-06')}") == ["An essay in June"]


async def test_a_run_with_no_words_to_rank_by_pages_on_its_cursor(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    for day in range(5):
        await story(feed_id, f"Day {day}", first_seen_at=NOW - day * DAY)

    seen: list[str] = []
    cursor = ""
    while True:
        page = (await _found("from:essays.example.com", after=cursor, limit=2)).listing
        seen += [entry.title for entry in page.entries]
        if not page.cursor:
            break
        cursor = page.cursor

    assert seen == ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4"]


async def test_what_has_aged_out_of_the_river_is_still_held(clean: None, feed, story):
    feed_id = await feed("wire.example.com", expires_after=2 * DAY)
    await story(feed_id, "Last week", first_seen_at=NOW - 7 * DAY)

    assert await _titles("from:wire.example.com") == ["Last week"]
    assert [entry.title for entry in (await ui.river(KINDLE)).entries] == []


async def test_the_state_flags_are_the_ones_already_on_the_row(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    read = await story(feed_id, "Opened", body="Some text.")
    await story(feed_id, "Untouched", body="Some text.")
    await ui.mark_opened(read)

    assert await _titles("is:read") == ["Opened"]
    assert await _titles("is:unread") == ["Untouched"]


@pytest.mark.parametrize(
    "zone",
    [
        pytest.param("Mars/Olympus", id="no-such-place"),
        # Python's tzdata knows 113 names this Postgres does not, and a browser can still
        # report one of the legacy aliases. Validating against the wrong copy was a 500.
        pytest.param("Asia/Calcutta", id="a-legacy-alias-python-alone-knows"),
        pytest.param("America/Buenos_Aires", id="another-of-them"),
    ],
)
async def test_a_zone_postgres_does_not_know_is_refused(clean: None, zone):
    with pytest.raises(ui.BadZone):
        await ui.contents(zone=zone)
    with pytest.raises(ui.BadZone):
        await _titles(_month("2026-06"), zone=zone)


# Two copies of tzdata deciding where midnight was is how a shelf comes to hold rows the
# contents page counted under the month before it. Postgres does both.
@pytest.mark.parametrize("zone", ["Australia/Sydney", "America/Edmonton", "Africa/Casablanca"])
async def test_the_month_a_row_is_counted_under_is_the_month_it_is_served_on(
    clean: None, feed, story, zone
):
    feed_id = await feed("wire.example.com")
    for month in range(1, 13):
        at = datetime.datetime(2026, month, 1, 6, 30, tzinfo=datetime.UTC)
        await story(feed_id, f"Month {month}", first_seen_at=at)

    for volume in (await ui.contents(zone=zone)).months:
        shelved = await _titles(_month(volume.month), zone=zone)
        assert len(shelved) == volume.items, f"{zone} {volume.month}"
