"""The one query path, and the shape of what it reached."""

import datetime

import pytest

from old_news import ui
from old_news.config import KindleSettings

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


def _named(counts) -> dict[str, int]:
    return {count.name: count.items for count in counts}


async def test_the_shape_counts_by_publication(clean: None, feed, story):
    await story(await feed("wire.example.com"), "A bulletin")
    await story(await feed("essays.example.com"), "An essay")

    shape = await ui.shape(asked=ui.parse(""))

    assert _named(shape.publications) == {"wire.example.com": 1, "essays.example.com": 1}


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

    assert await _titles("from:gone.example.com") == ["From before"]
    assert _named((await ui.shape(asked=ui.parse(""))).publications) == {"gone.example.com": 1}


# With its own filter applied a facet would only ever count the value already chosen,
# and switching publication would mean clearing the query first.
async def test_a_dimension_is_counted_without_its_own_filter(clean: None, feed, story):
    await story(await feed("wire.example.com"), "A bulletin")
    await story(await feed("essays.example.com"), "An essay")

    shape = await ui.shape(asked=ui.parse("from:essays.example.com"))

    assert _named(shape.publications) == {"wire.example.com": 1, "essays.example.com": 1}


async def test_but_the_other_dimensions_still_narrow_it(clean: None, feed, story):
    wire = await feed("wire.example.com")
    essays = await feed("essays.example.com")
    june = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    await story(wire, "A bulletin in June", first_seen_at=june)
    await story(essays, "An essay in July", first_seen_at=june + 30 * DAY)

    shape = await ui.shape(asked=ui.parse(f"from:essays.example.com {_month('2026-06')}"))

    assert _named(shape.publications) == {"wire.example.com": 1}


async def test_a_month_is_a_pair_of_dates(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "In June", first_seen_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "In July", first_seen_at=datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
    )

    assert await _titles(_month("2026-06")) == ["In June"]


async def test_the_shape_lists_what_is_in_each_month(clean: None, feed, story):
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "In June", first_seen_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)
    )
    await story(
        feed_id, "In July", first_seen_at=datetime.datetime(2026, 7, 15, tzinfo=datetime.UTC)
    )

    months = (await ui.shape(asked=ui.parse(""))).months

    assert sorted((count.name, count.items) for count in months) == [
        ("2026-06", 1),
        ("2026-07", 1),
    ]


async def test_a_month_is_grouped_in_the_readers_own_zone(clean: None, feed, story):
    """22.00 UTC on the 31st is already the 1st in Sydney, and the shelf has to say so."""
    feed_id = await feed("wire.example.com")
    await story(
        feed_id, "Late July", first_seen_at=datetime.datetime(2026, 7, 31, 22, tzinfo=datetime.UTC)
    )

    assert [count.name for count in (await ui.shape(asked=ui.parse(""), zone=SYDNEY)).months] == [
        "2026-08"
    ]
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


async def test_the_shape_counts_the_states_too(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    read = await story(feed_id, "Opened", body="Some text.")
    await story(feed_id, "Untouched", body="Some text.")
    await ui.mark_opened(read)

    states = _named((await ui.shape(asked=ui.parse(""))).states)

    assert (states["read"], states["unread"], states["finished"]) == (1, 1, 0)


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
        await ui.shape(asked=ui.parse(""), zone=zone)
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

    for count in (await ui.shape(asked=ui.parse(""), zone=zone)).months:
        served = await _titles(_month(count.name), zone=zone, limit=100)
        assert len(served) == count.items, f"{zone} {count.name}"


# The rail once reported the whole archive against a result of forty-five, because the
# words are applied by the ranking join and counting has no join to apply them with.
async def test_the_shape_counts_only_what_the_words_reached(clean: None, feed, story):
    wire = await feed("wire.example.com")
    essays = await feed("essays.example.com")
    await story(wire, "A bulletin", body="Nothing about housing at all.")
    await story(wire, "Another bulletin", body="Still nothing.")
    await story(essays, "An essay", body="Housing density fell.")

    shape = await ui.shape(asked=ui.parse("density"))

    assert _named(shape.publications) == {"essays.example.com": 1}
