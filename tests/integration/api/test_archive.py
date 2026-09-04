"""The archive over HTTP: a contents page, and shelves that refuse to be everything."""

import datetime

import pytest

from old_news.db import Tier

JUNE = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)


async def test_the_contents_shelves_by_publication_and_month(served, feed, story):
    await story(await feed("essays.example.com", tier=Tier.KINDLE), "An essay", first_seen_at=JUNE)

    body = (await (await served()).get("/archive")).json()

    assert body["items"] == 1
    assert body["months"] == [{"month": "2026-06", "items": 1}]
    assert [(run["title"], run["tier"], run["items"]) for run in body["feeds"]] == [
        ("essays.example.com", Tier.KINDLE, 1)
    ]


async def test_a_publications_shelf_serialises_a_row_whole(served, feed, story):
    feed_id = await feed("essays.example.com", category="Essays")
    await story(feed_id, "A headline", body="Text.")

    response = await (await served()).get("/archive/items", params={"feed": str(feed_id)})

    assert response.json()["entries"][0]["title"] == "A headline"


async def test_a_months_shelf_is_asked_for_by_name(served, feed, story):
    await story(await feed("wire.example.com"), "In June", first_seen_at=JUNE)

    response = await (await served()).get("/archive/items", params={"month": "2026-06"})

    assert [entry["title"] for entry in response.json()["entries"]] == ["In June"]


async def test_a_shelf_of_everything_is_a_bad_request(client):
    assert (await client.get("/archive/items")).status_code == 400


async def test_an_impossible_month_is_a_bad_request(client):
    assert (await client.get("/archive/items", params={"month": "2026-13"})).status_code == 400


async def test_an_unusable_zone_is_a_bad_request(client):
    assert (await client.get("/archive", params={"zone": "Mars/Olympus"})).status_code == 400


async def test_a_forged_cursor_is_a_bad_request(client):
    params = {"month": "2026-06", "after": "not-a-cursor"}

    assert (await client.get("/archive/items", params=params)).status_code == 400


async def test_search_serves_what_matched_with_a_count(served, feed, story):
    feed_id = await feed("essays.example.com")
    await story(feed_id, "A quiet street", body="Housing density fell on this street.")
    await story(feed_id, "A loud garden", body="Wrens, mostly.")

    body = (await (await served()).get("/archive/search", params={"q": "density"})).json()

    assert body["total"] == 1
    assert [entry["title"] for entry in body["listing"]["entries"]] == ["A quiet street"]
    assert "density" in body["listing"]["entries"][0]["snippet"]


async def test_a_search_for_nothing_is_a_bad_request(client):
    assert (await client.get("/archive/search", params={"q": "  "})).status_code == 400


# Every one of these was a 500 before: an exception the handler does not catch reaches the
# client as "internal server error" over a query string anyone could type.
@pytest.mark.parametrize(
    ("path", "params"),
    [
        pytest.param("/archive/search", {"q": "density", "after": "nonsense"}, id="after-words"),
        pytest.param(
            "/archive/search", {"q": "density", "after": "\u00b2"}, id="after-a-digit-int-refuses"
        ),
        pytest.param(
            "/archive/search",
            {"q": "density", "after": "9999999999999999999"},
            id="after-past-a-bigint",
        ),
        pytest.param("/archive/items", {"month": "9999-12"}, id="month-past-the-last-one"),
        pytest.param("/archive/items", {"month": "2026-06-15"}, id="a-day-as-a-month"),
        pytest.param("/archive", {"zone": "Asia/Calcutta"}, id="a-zone-only-python-knows"),
        pytest.param(
            "/archive/items",
            {"month": "2026-06", "zone": "Asia/Calcutta"},
            id="the-same-on-a-shelf",
        ),
    ],
)
async def test_what_cannot_be_served_is_a_bad_request_not_a_500(client, path, params):
    assert (await client.get(path, params=params)).status_code == 400
