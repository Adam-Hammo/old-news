"""The reading routes: what binds, what 404s, and what a bad cursor does."""

import uuid

from litestar.testing import AsyncTestClient


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
