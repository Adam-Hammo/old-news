from collections.abc import AsyncIterator

import pytest
from logfire.testing import CaptureLogfire

from old_news.config.http import HttpSettings
from old_news.fetch import Fetcher, Response, TooLarge
from old_news.observability import telemetry

BODY = b"<html><body>hello</body></html>"
ETAG = '"v1"'


ROUTES = {
    "/conditional": lambda headers: (
        (304, b"", {"ETag": ETAG})
        if headers.get("if-none-match") == ETAG
        else (200, BODY, {"ETag": ETAG, "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"})
    ),
    "/huge": (200, b"x" * 5000, {}),
    "/redirect": (302, b"", {"Location": "/conditional"}),
    "/boom": (500, b"nope", {}),
}


@pytest.fixture
def server(http_server) -> str:
    return http_server(ROUTES)


@pytest.fixture
async def fetcher() -> AsyncIterator[Fetcher]:
    client = Fetcher(HttpSettings(max_body_bytes=1024))
    yield client
    await client.aclose()


async def test_plain_get(fetcher: Fetcher, server: str):
    response = await fetcher.get(f"{server}/conditional")

    assert response.ok
    assert response.body == BODY
    assert response.etag == ETAG
    assert response.last_modified is not None


async def test_etag_yields_304(fetcher: Fetcher, server: str):
    first = await fetcher.get(f"{server}/conditional")
    second = await fetcher.get(f"{server}/conditional", etag=first.etag)

    assert second.not_modified
    assert second.body == b""


async def test_error_status_is_a_response_not_an_exception(fetcher: Fetcher, server: str):
    response = await fetcher.get(f"{server}/boom")

    assert response.status == 500
    assert not response.ok


async def test_follows_redirects(fetcher: Fetcher, server: str):
    response = await fetcher.get(f"{server}/redirect")

    assert response.ok
    assert response.url.endswith("/conditional")


async def test_body_cap_is_enforced(fetcher: Fetcher, server: str):
    with pytest.raises(TooLarge):
        await fetcher.get(f"{server}/huge")


def test_header_lookup_is_case_insensitive():
    response = Response(status=200, url="http://x", body=b"", headers={"ETaG": "abc"})

    assert response.etag == "abc"
    assert response.header("etag") == "abc"
    assert response.header("missing") is None


@pytest.fixture
async def traced_fetcher(capfire: CaptureLogfire) -> AsyncIterator[Fetcher]:
    """Telemetry has to be on before the client is built — `instrument_http_client`
    no-ops otherwise, exactly as it does when the app runs with telemetry disabled."""
    telemetry._enabled = True
    client = Fetcher(HttpSettings(max_body_bytes=1024))
    capfire.exporter.exported_spans.clear()
    yield client
    await client.aclose()
    telemetry._enabled = False


def _finished(capfire: CaptureLogfire) -> list[str]:
    return [
        span.name
        for span in capfire.exporter.exported_spans
        if (span.attributes or {}).get("logfire.span_type") != "pending_span"
    ]


async def test_the_client_itself_is_traced(traced_fetcher: Fetcher, server: str, capfire):
    """The hand-rolled span carries the domain — which feed, redacted, conditional or
    not. The client span underneath it carries the transport."""
    await traced_fetcher.get(f"{server}/conditional")

    names = _finished(capfire)
    assert "GET feed" in names
    assert len(names) > 1, f"no client span beneath the feed span: {names}"


async def test_only_this_client_is_instrumented(capfire: CaptureLogfire, server: str):
    """Instrumenting the instance rather than the library: a client built while
    telemetry is off stays silent."""
    telemetry._enabled = False
    quiet = Fetcher(HttpSettings(max_body_bytes=1024))
    capfire.exporter.exported_spans.clear()
    try:
        await quiet.get(f"{server}/conditional")
    finally:
        await quiet.aclose()

    assert _finished(capfire) == ["GET feed"]


SECRET = "SUPERSECRET"


async def test_the_feed_span_never_carries_the_query_string(
    traced_fetcher: Fetcher, server: str, capfire: CaptureLogfire
):
    """`url.redacted` is built by hand for this reason: span attributes are not
    scrubbed, so the query string must never be put in one."""
    await traced_fetcher.get(f"{server}/conditional?api_key={SECRET}")

    ours = [s for s in capfire.exporter.exported_spans if s.name == "GET feed"]
    emitted = str([s.attributes for s in ours])

    assert SECRET not in emitted
    assert "/conditional" in emitted


async def test_the_client_span_does_carry_the_query_string(
    traced_fetcher: Fetcher, server: str, capfire: CaptureLogfire
):
    """The accepted cost of instrumenting httpx2: its span records `http.url` whole,
    and Logfire treats that key as safe and never scrubs it. Feed URLs are ours and
    hold no credentials. This fails the day one does, which is the point of it.
    """
    await traced_fetcher.get(f"{server}/conditional?api_key={SECRET}")

    theirs = [s for s in capfire.exporter.exported_spans if s.name != "GET feed"]
    assert SECRET in str([s.attributes for s in theirs])
