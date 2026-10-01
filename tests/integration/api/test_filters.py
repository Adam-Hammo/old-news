"""The Filters tab's half of the contract."""

import uuid

import pytest

from old_news.subscriptions.service import add

LIVE = {"dimension": "url_pattern", "pattern": "/live/"}


async def _filtering(client) -> list[dict]:
    response = await client.get("/filters")
    assert response.status_code == 200
    return response.json()


async def test_a_filter_is_added_listed_and_removed(served):
    feed = await add("https://example.com/feed.xml", title="Example")
    assert feed is not None
    client = await served()

    added = await client.post(
        "/filters", json={**LIVE, "pattern": "  /live/  ", "feed_id": str(feed.id)}
    )
    assert added.status_code == 201
    [listed] = await _filtering(client)
    assert (listed["pattern"], listed["feed"], listed["source"]) == ("/live/", "Example", "hand")

    assert (await client.delete(f"/filters/{listed['id']}")).status_code == 204
    assert await _filtering(client) == []
    assert (await client.delete(f"/filters/{listed['id']}")).status_code == 404


async def test_the_same_filter_twice_is_a_conflict(served):
    client = await served()

    assert (await client.post("/filters", json=LIVE)).status_code == 201
    assert (await client.post("/filters", json=LIVE)).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {**LIVE, "dimension": "author"},
        {**LIVE, "pattern": "   "},
        {**LIVE, "feed_id": str(uuid.uuid4())},
    ],
    ids=["unknown dimension", "blank pattern", "unknown feed"],
)
async def test_a_filter_that_cannot_work_is_refused(client, body):
    assert (await client.post("/filters", json=body)).status_code == 400
