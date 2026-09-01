"""What a browser says went wrong, and where it lands."""

import logging

from litestar.testing import AsyncTestClient

from old_news.api.routes.reports import MESSAGE_CHARS

REPORT = {
    "kind": "error",
    "message": "TypeError: undefined is not an object",
    "url": "/item/01a05a10-bc94-7667-b866-c15d2f3a7e14",
    "display": "standalone",
    "since_visible": 40,
}


async def test_a_report_is_accepted_and_logged(client: AsyncTestClient, caplog):
    with caplog.at_level(logging.WARNING):
        response = await client.post("/client-reports", json=REPORT)

    assert response.status_code == 204
    assert "standalone" in caplog.text
    assert "undefined is not an object" in caplog.text


async def test_a_report_that_says_nothing_useful_is_refused(client: AsyncTestClient):
    response = await client.post("/client-reports", json={"kind": "error"})

    assert response.status_code == 400


# A client in a loop must not be able to write log lines without limit.
async def test_a_runaway_message_is_cut(client: AsyncTestClient, caplog):
    with caplog.at_level(logging.WARNING):
        await client.post("/client-reports", json={**REPORT, "message": "x" * 10_000})

    assert "x" * MESSAGE_CHARS in caplog.text
    assert "x" * (MESSAGE_CHARS + 1) not in caplog.text
