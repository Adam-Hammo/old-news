"""The reading routes: what binds, what 404s, and what a bad cursor does."""

import datetime
import uuid

from litestar.testing import AsyncTestClient

from old_news.db import Tier


async def test_the_river_serialises_a_row_whole(served, feed, story):
    await story(await feed("outlet.example.com", category="Technology"), "A headline", body="Text.")

    response = await (await served()).get("/river")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["title"] == "A headline"
    assert entry["outlet"] == "outlet.example.com"
    assert entry["read"] is False


async def test_the_section_parameter_binds(served, feed, story):
    await story(await feed("tech.example.com", category="Technology"), "A chip")
    await story(await feed("science.example.com", category="Science"), "A telescope")

    response = await (await served()).get("/river", params={"section": "Science"})

    assert [entry["title"] for entry in response.json()["entries"]] == ["A telescope"]


async def test_sections_are_served(served, feed):
    await feed("tech.example.com", category="Technology")

    response = await (await served()).get("/sections")

    assert response.json() == ["Technology"]


async def test_opening_an_article_records_it(served, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline", body="Text.")
    client = await served()

    opened = await client.post(f"/items/{item_id}/opened")
    article = await client.get(f"/items/{item_id}")

    assert opened.status_code == 201
    assert opened.json()["read_at"]
    assert article.json()["read"] is True
    assert article.json()["feed_body"] == "Text."


async def test_a_limit_past_the_ceiling_is_refused(client: AsyncTestClient):
    response = await client.get("/river", params={"limit": 5000})

    assert response.status_code == 400


async def test_a_forged_cursor_is_a_client_error(client: AsyncTestClient):
    response = await client.get("/river", params={"after": "nonsense!"})

    assert response.status_code == 400


async def test_an_item_that_is_not_there_is_a_404(client: AsyncTestClient):
    missing = uuid.uuid4()

    assert (await client.get(f"/items/{missing}")).status_code == 404
    assert (await client.post(f"/items/{missing}/opened")).status_code == 404


async def test_reading_to_the_bottom_is_recorded(served, feed, story):
    item_id = await story(await feed("outlet.example.com"), "A headline", body="Text.")
    client = await served()

    finished = await client.post(f"/items/{item_id}/finished")
    article = await client.get(f"/items/{item_id}")

    assert finished.status_code == 201
    assert finished.json()["finished_at"]
    assert article.json()["read"] is True


async def test_the_archive_serves_what_the_river_has_dropped(served, feed, story):
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
    feed_id = await feed("outlet.example.com", expires_after=datetime.timedelta(days=2))
    await story(feed_id, "Aged out", first_seen_at=old)
    client = await served()

    river = await client.get("/river")
    archive = await client.get("/river", params={"archive": True})

    assert river.json()["entries"] == []
    assert [entry["title"] for entry in archive.json()["entries"]] == ["Aged out"]


async def test_a_row_says_whether_an_issue_has_it(served, feed, story):
    feed_id = await feed("essays.example.com", tier=Tier.KINDLE)
    await story(feed_id, "An essay", body="Text.")
    client = await served()

    entry = (await client.get("/river")).json()["entries"][0]

    assert (entry["sent"], entry["queued"]) == (False, True)


async def test_marking_an_item_that_is_not_there_finished_is_a_404(client: AsyncTestClient):
    assert (await client.post(f"/items/{uuid.uuid4()}/finished")).status_code == 404


async def test_a_held_image_is_served_from_the_archive(served, feed, story, held_image):
    item_id = await story(await feed("essays.example.com"), "An essay", body="Text.")
    capture_id = await held_image(item_id, "https://cdn.example.com/a.png")
    client = await served()

    response = await client.get(f"/images/{capture_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "immutable" in response.headers["cache-control"]
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_an_articles_pictures_point_at_the_copy_we_hold(served, feed, story, held_image):
    url = "https://cdn.example.com/a.png"
    item_id = await story(
        await feed("essays.example.com"), "An essay", body=f"Text.\n\n![a chart]({url})\n"
    )
    capture_id = await held_image(item_id, url)
    client = await served()

    article = (await client.get(f"/items/{item_id}")).json()

    assert f"](/images/{capture_id}/)" in article["feed_body"]
    assert url not in article["feed_body"]


async def test_a_picture_nothing_is_held_for_stays_with_the_publisher(served, feed, story):
    """Better a publisher's copy that may still work than no picture at all."""
    url = "https://cdn.example.com/gone.png"
    item_id = await story(
        await feed("essays.example.com"), "An essay", body=f"Text.\n\n![a chart]({url})\n"
    )
    client = await served()

    article = (await client.get(f"/items/{item_id}")).json()

    assert url in article["feed_body"]


async def test_an_image_that_is_not_there_is_a_404(client: AsyncTestClient):
    assert (await client.get(f"/images/{uuid.uuid4()}")).status_code == 404


async def test_a_held_lead_is_offered_to_the_article(served, feed, story, held_image):
    item_id = await story(await feed("essays.example.com"), "An essay", body="Text.")
    capture_id = await held_image(item_id, "https://cdn.example.com/hero.png", role="lead")
    client = await served()

    article = (await client.get(f"/items/{item_id}")).json()

    assert article["lead"] == f"/images/{capture_id}/"


async def test_a_lead_the_reading_already_carries_is_not_offered_twice(
    served, feed, story, held_image
):
    """Some publishers put the hero in the body as well."""
    url = "https://cdn.example.com/hero.png"
    item_id = await story(
        await feed("essays.example.com"), "An essay", body=f"![hero]({url})\n\nText.\n"
    )
    await held_image(item_id, url, role="lead")
    client = await served()

    article = (await client.get(f"/items/{item_id}")).json()

    assert article["lead"] == ""
    assert "/images/" in article["feed_body"], "but it is still served from the archive"


async def test_an_article_with_no_held_picture_offers_no_lead(served, feed, story):
    item_id = await story(await feed("essays.example.com"), "An essay", body="Text.")
    client = await served()

    assert (await client.get(f"/items/{item_id}")).json()["lead"] == ""
