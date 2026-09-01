"""The settings screen's half of the contract."""

import uuid

from old_news.subscriptions.service import add

FEED = "https://example.com/feed.xml"


async def _following(client) -> list[dict]:
    response = await client.get("/subscriptions")
    assert response.status_code == 200
    return response.json()


async def test_what_we_follow_is_listed_filed(served):
    await add(FEED, title="Example", category="Technology")
    client = await served()

    assert [(f["title"], f["category"]) for f in await _following(client)] == [
        ("Example", "Technology")
    ]


async def test_a_feed_can_be_filed_from_the_screen(served):
    feed = await add(FEED, category="Technology")
    assert feed is not None
    client = await served()

    response = await client.patch(f"/subscriptions/{feed.id}", json={"category": "Science"})

    assert response.status_code == 204
    assert [f["category"] for f in await _following(client)] == ["Science"]


async def test_a_feed_can_be_dropped_from_the_screen(served):
    feed = await add(FEED)
    assert feed is not None
    client = await served()

    response = await client.delete(f"/subscriptions/{feed.id}")

    assert response.status_code == 204
    assert await _following(client) == []


async def test_filing_something_we_do_not_follow_is_a_404(served):
    client = await served()

    response = await client.patch(f"/subscriptions/{uuid.uuid4()}", json={"category": "Science"})

    assert response.status_code == 404


async def test_dropping_something_we_do_not_follow_is_a_404(served):
    client = await served()

    response = await client.delete(f"/subscriptions/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_following_something_already_followed_says_which(served):
    await add(FEED)
    client = await served()

    response = await client.post("/subscriptions", json={"url": FEED})

    assert response.status_code == 409


async def test_an_address_we_cannot_poll_is_refused(served):
    client = await served()

    response = await client.post("/subscriptions", json={"url": "mailto:someone@example.com"})

    assert response.status_code == 400
