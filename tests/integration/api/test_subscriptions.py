"""The settings screen's half of the contract."""

import uuid

from old_news.db import LONGEST_WINDOW
from old_news.subscriptions.service import add

FEED = "https://example.com/feed.xml"
# Every choice at once, which is the only shape the route takes.
FILING = {"category": "Science", "tier": "wire", "expires_after_seconds": 3600}


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

    response = await client.patch(f"/subscriptions/{feed.id}", json=FILING)

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

    response = await client.patch(f"/subscriptions/{uuid.uuid4()}", json=FILING)

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


async def test_a_feed_is_filed_with_its_tier_and_window_in_one_call(served):
    feed = await add(FEED, title="An essay", category="Edition")
    assert feed is not None
    client = await served()

    filed = await client.patch(
        f"/subscriptions/{feed.id}",
        json={"category": "Essays", "tier": "kindle", "expires_after_seconds": 1209600},
    )
    listed = (await client.get("/subscriptions")).json()[0]

    assert filed.status_code == 204
    assert (listed["category"], listed["tier"], listed["expires_after_seconds"]) == (
        "Essays",
        "kindle",
        1209600,
    )


async def test_a_feed_arrives_at_the_cheap_end(served):
    """No picture past the lead is fetched, and it ages out at the longest window there is."""
    await add(FEED)
    client = await served()

    listed = (await client.get("/subscriptions")).json()[0]

    assert (listed["tier"], listed["expires_after_seconds"]) == (
        "wire",
        int(LONGEST_WINDOW.total_seconds()),
    )


async def test_a_window_longer_than_the_river_holds_is_refused(served):
    """Past the ceiling is the archive's job, so there is no window that says forever."""
    feed = await add(FEED)
    assert feed is not None
    client = await served()

    response = await client.patch(
        f"/subscriptions/{feed.id}",
        json={"category": "", "expires_after_seconds": int(LONGEST_WINDOW.total_seconds()) + 1},
    )

    assert response.status_code == 400


async def test_a_tier_that_is_not_one_is_refused(served):
    feed = await add(FEED)
    assert feed is not None
    client = await served()

    response = await client.patch(
        f"/subscriptions/{feed.id}",
        json={"category": "", "tier": "whenever", "expires_after_seconds": 3600},
    )

    assert response.status_code == 400
