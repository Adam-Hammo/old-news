import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import logfire
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from old_news.config.http import HttpSettings
from old_news.fetch import Fetcher, Response, TooLarge

BODY = b"<html><body>hello</body></html>"
ETAG = '"v1"'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/conditional":
            if self.headers.get("If-None-Match") == ETAG:
                self.send_response(304)
                self.send_header("ETag", ETAG)
                self.end_headers()
                return
            self._send(200, BODY, {"ETag": ETAG, "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"})
        elif self.path == "/huge":
            self._send(200, b"x" * 5000)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/conditional")
            self.end_headers()
        elif self.path == "/boom":
            self._send(500, b"nope")
        else:
            self._send(404, b"")

    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


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


async def test_the_fetch_span_never_carries_the_query_string(fetcher: Fetcher, server: str):
    """A feed URL's query string can hold an API key, and span attributes aren't scrubbed."""
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

    await fetcher.get(f"{server}/conditional?api_key=SUPERSECRET")

    emitted = str([s.attributes for s in exporter.exported_spans])
    assert "SUPERSECRET" not in emitted
    assert "/conditional" in emitted
