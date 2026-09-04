"""Keyword search: what the terms reach, what ranks first, and what a fragment reads like."""

import datetime

import pytest

from old_news import ui
from old_news.config import KindleSettings
from old_news.db import Tier

KINDLE = KindleSettings()

DENSITY = "The street was rebuilt for cars. Housing density fell, and the shops went with it."
BIRDS = "A haven for wildlife, mostly wrens and a great deal of unexplained noise."


async def _titles(terms: str, **kwargs) -> list[str]:
    found = await ui.look(KINDLE, terms=terms, **kwargs)
    return [entry.title for entry in found.listing.entries]


async def test_a_word_in_the_reading_finds_the_article(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=DENSITY)
    await story(feed_id, "A loud garden", body=BIRDS)

    assert await _titles("density") == ["A quiet street"]


async def test_a_word_in_the_headline_finds_it_too(clean: None, feed, story):
    """The headline is the half of an article a reader is most likely to remember."""
    feed_id = await feed("essays.example.com")
    await story(feed_id, "Everything about wombats", body=DENSITY)

    assert await _titles("wombats") == ["Everything about wombats"]


# Two words typed into an archive are both meant. Either-of-them is what makes a search
# over a hundred thousand rows useless.
async def test_every_word_has_to_be_there(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=DENSITY)
    await story(feed_id, "A loud garden", body=BIRDS)

    assert await _titles("density wrens") == []
    assert await _titles("density housing") == ["A quiet street"]


async def test_a_headline_match_outranks_a_reading_one(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=f"{DENSITY} {DENSITY} {DENSITY}")
    await story(feed_id, "Housing density, at last", body=BIRDS)

    assert (await _titles("housing density"))[0] == "Housing density, at last"


async def test_the_count_is_of_everything_that_matched_not_of_the_page(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    for number in range(5):
        await story(feed_id, f"Street {number}", body=DENSITY)

    found = await ui.look(KINDLE, terms="density", limit=2)

    assert (len(found.listing.entries), found.total) == (2, 5)


async def test_results_page_to_their_end(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    for number in range(5):
        await story(feed_id, f"Street {number}", body=DENSITY)

    seen: list[str] = []
    cursor = ""
    while True:
        found = await ui.look(KINDLE, terms="density", after=cursor, limit=2)
        seen += [entry.title for entry in found.listing.entries]
        if not found.listing.cursor:
            break
        cursor = found.listing.cursor

    assert sorted(seen) == ["Street 0", "Street 1", "Street 2", "Street 3", "Street 4"]


async def test_a_fragment_of_the_article_says_why_it_matched(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=DENSITY)

    entry = (await ui.look(KINDLE, terms="density")).listing.entries[0]

    assert f"{ui.OPEN}density{ui.CLOSE}" in entry.snippet


async def test_a_fragment_is_prose_rather_than_the_markdown_it_is_stored_as(
    clean: None, feed, story
):
    feed_id = await feed("essays.example.com")
    await story(
        feed_id,
        "A quiet street",
        body="## Head\n\nThe [density](https://example.com/x) of Google&#x27;s streets fell.",
    )

    entry = (await ui.look(KINDLE, terms="density")).listing.entries[0]

    assert "https://" not in entry.snippet
    assert "&#x27;" not in entry.snippet
    assert "Google's" in entry.snippet


async def test_what_has_aged_out_of_the_river_is_still_searchable(clean: None, feed, story):
    """Expiry hides. Search is the other way back to what it hid."""
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=90)
    feed_id = await feed("wire.example.com", expires_after=datetime.timedelta(days=2))
    await story(feed_id, "A quiet street", body=DENSITY, first_seen_at=old)

    assert await _titles("density") == ["A quiet street"]
    assert [entry.title for entry in (await ui.river(KINDLE)).entries] == []


async def test_a_dropped_feeds_articles_are_still_searchable(clean: None, feed, story):
    feed_id = await feed("gone.example.com", active=False)
    await story(feed_id, "A quiet street", body=DENSITY)

    assert await _titles("density") == ["A quiet street"]


async def test_a_row_still_says_what_the_book_has_done_with_it(clean: None, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "A quiet street", body=DENSITY)

    entry = (await ui.look(KINDLE, terms="density")).listing.entries[0]

    assert (entry.sent, entry.queued) == (False, True)


# Query syntax would make a colon into a field name and a stray quote into a parse error.
async def test_punctuation_in_what_was_typed_is_just_words(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=DENSITY)

    assert await _titles('density: "housing') == ["A quiet street"]


# A liveblog rewrites its headline every few hours. Matching a superseded one surfaces an
# article whose headline says something else entirely, with no fragment to explain it.
async def test_a_headline_that_has_been_rewritten_is_not_what_search_matches(
    clean: None, feed, story, supersede
):
    feed_id = await feed("wire.example.com")
    item_id = await story(feed_id, "Tariff talks collapse", body=BIRDS)
    await supersede(item_id, "Who is calling the shots on trade")

    assert await _titles("tariff") == []
    assert (await ui.look(KINDLE, terms="tariff")).total == 0
    assert await _titles("shots") == ["Who is calling the shots on trade"]


async def test_a_reading_of_a_superseded_version_is_not_searched_either(
    clean: None, feed, story, supersede
):
    feed_id = await feed("wire.example.com")
    item_id = await story(feed_id, "A quiet street", body=DENSITY)
    await supersede(item_id, "A quiet street", body=BIRDS)

    assert await _titles("density") == []
    assert await _titles("wrens") == ["A quiet street"]


# A title score and a body score come off two different indexes and are not on one scale,
# so a body score must never decide the order inside the headline group.
async def test_a_body_score_does_not_order_the_headline_group(clean: None, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "Density itself", body="A word about nothing much.")
    await story(feed_id, "Density and more", body=" ".join(["density"] * 200))

    assert (await _titles("density"))[0] == "Density itself"


@pytest.mark.parametrize("terms", ["", "   "])
async def test_searching_for_nothing_is_refused(clean: None, terms):
    with pytest.raises(ui.BadQuery):
        await ui.look(KINDLE, terms=terms)


@pytest.mark.parametrize(
    "after",
    [
        pytest.param("nonsense", id="not-a-number"),
        # `isdigit` is true for these and `int` refuses them, which used to be a 500.
        pytest.param("\u00b2", id="superscript-two"),
        pytest.param("\u0663", id="arabic-indic-three"),
        pytest.param("9999999999999999999", id="past-what-a-bigint-holds"),
    ],
)
async def test_a_page_that_is_not_a_number_is_refused(clean: None, after):
    with pytest.raises(ui.BadQuery):
        await ui.look(KINDLE, terms="density", after=after)


async def test_paging_stops_rather_than_running_forever(clean: None, feed, story):
    """The cursor is not offered past the depth anyone would page to."""
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body=DENSITY)

    found = await ui.look(KINDLE, terms="density", after=str(ui.MAX_DEPTH), limit=1)

    assert found.listing.cursor == ""
