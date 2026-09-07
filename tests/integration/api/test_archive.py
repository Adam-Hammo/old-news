"""The archive over HTTP: a contents page, and one query that reaches whatever it reaches."""

import datetime

import pytest

from old_news.db import Tier

JUNE = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)


async def test_the_contents_counts_by_publication_and_month(served, feed, story):
    await story(await feed("essays.example.com", tier=Tier.KINDLE), "An essay", first_seen_at=JUNE)

    body = (await (await served()).get("/archive")).json()

    assert body["items"] == 1
    assert body["months"] == [{"month": "2026-06", "items": 1}]
    assert [(run["title"], run["tier"], run["items"]) for run in body["feeds"]] == [
        ("essays.example.com", Tier.KINDLE, 1)
    ]


async def test_a_publication_serialises_a_row_whole(served, feed, story):
    await story(await feed("essays.example.com", category="Essays"), "A headline", body="Text.")

    params = {"q": "from:essays.example.com"}
    response = await (await served()).get("/archive/items", params=params)

    assert response.json()["listing"]["entries"][0]["title"] == "A headline"


async def test_a_month_is_a_pair_of_dates(served, feed, story):
    await story(await feed("wire.example.com"), "In June", first_seen_at=JUNE)

    params = {"q": "after:2026-06 before:2026-07"}
    body = (await (await served()).get("/archive/items", params=params)).json()

    assert [entry["title"] for entry in body["listing"]["entries"]] == ["In June"]


# It used to be a 400. Everything held is what the archive opens on now.
async def test_asking_for_nothing_is_everything_held(served, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "An essay", body="Text.")
    await story(feed_id, "Another", body="More text.")

    body = (await (await served()).get("/archive/items")).json()

    assert body["total"] == 2
    assert len(body["listing"]["entries"]) == 2


async def test_words_come_back_with_a_count_and_a_fragment(served, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body="Housing density fell on this street.")
    await story(feed_id, "A loud garden", body="Wrens, mostly.")

    body = (await (await served()).get("/archive/items", params={"q": "density"})).json()

    assert body["total"] == 1
    assert [entry["title"] for entry in body["listing"]["entries"]] == ["A quiet street"]
    assert "density" in body["listing"]["entries"][0]["snippet"]


# The two that used to do the opposite of what they said.
async def test_a_minus_excludes_over_the_wire(served, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body="Housing density fell here.")
    await story(feed_id, "A loud street", body="Housing density rose, say the Liberals.")

    params = {"q": "density -liberals"}
    body = (await (await served()).get("/archive/items", params=params)).json()

    assert [entry["title"] for entry in body["listing"]["entries"]] == ["A quiet street"]


async def test_a_quoted_run_has_to_be_adjacent(served, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "Together", body="It was cheap to mandate and expensive to own.")
    await story(feed_id, "Apart", body="Cheap, they said. Nobody had to mandate anything.")

    params = {"q": '"cheap to mandate"'}
    body = (await (await served()).get("/archive/items", params=params)).json()

    assert [entry["title"] for entry in body["listing"]["entries"]] == ["Together"]


async def test_an_unusable_zone_is_a_bad_request(client):
    assert (await client.get("/archive", params={"zone": "Mars/Olympus"})).status_code == 400


async def test_a_forged_cursor_is_a_bad_request(client):
    params = {"q": "from:nobody", "after": "not-a-cursor"}

    assert (await client.get("/archive/items", params=params)).status_code == 400


# Every one of these was a 500 before: an exception the handler does not catch reaches the
# client as "internal server error" over a query string anyone could type.
@pytest.mark.parametrize(
    ("path", "params"),
    [
        pytest.param("/archive/items", {"q": "density", "after": "nonsense"}, id="after-words"),
        pytest.param(
            "/archive/items", {"q": "density", "after": "²"}, id="after-a-digit-int-refuses"
        ),
        pytest.param(
            "/archive/items",
            {"q": "density", "after": "9999999999999999999"},
            id="after-past-a-bigint",
        ),
        pytest.param("/archive/items", {"q": "before:10000-01"}, id="past-the-last-month"),
        pytest.param("/archive/items", {"q": "after:banana"}, id="not-a-date"),
        pytest.param("/archive/items", {"q": "is:interesting"}, id="not-a-state"),
        pytest.param("/archive", {"zone": "Asia/Calcutta"}, id="a-zone-only-python-knows"),
        pytest.param(
            "/archive/items",
            {"q": "after:2026-06", "zone": "Asia/Calcutta"},
            id="the-same-on-a-query",
        ),
    ],
)
async def test_what_cannot_be_served_is_a_bad_request_not_a_500(client, path, params):
    assert (await client.get(path, params=params)).status_code == 400
