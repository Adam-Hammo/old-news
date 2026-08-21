import os
import random
import threading
import zlib
from collections.abc import Callable, Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from factory.random import reseed_random

# Ryuk bind-mounts the docker socket, which Docker Desktop on macOS refuses.
# testcontainers reads its config at import, so this must run first.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# Real publisher pages, checked in whole. Shared rather than sitting beside one suite:
# the extractor is unit-tested against them and the extraction path integration-tested
# against the same bytes, and trimming them to fit a directory would change what they
# prove.
PAGES = Path(__file__).parent / "pages"

# A fresh draw per run, so every run is a chance to build a shape no run has built before.
# That only works if a red one can be replayed, which is what the two hooks below are for:
# the seed goes in the header and again beside the failures.
SEED = int(os.environ.get("OLD_NEWS_TEST_SEED") or random.randrange(2**31))

REPLAY = f"OLD_NEWS_TEST_SEED={SEED}"


def pytest_report_header() -> str:
    return f"test data seed: {SEED}  ({REPLAY} to replay this run)"


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Restated at the bottom, because that is where a failure is read from."""
    if terminalreporter.stats.get("failed") or terminalreporter.stats.get("error"):
        terminalreporter.write_line(f"replay: {REPLAY} just test")


@pytest.fixture(autouse=True)
def entropy(request: pytest.FixtureRequest) -> int:
    """Reseeded per test off its own node id, so replaying the run reproduces every row and
    `-k one_test` on its own builds exactly what it built inside the full run."""
    seed = SEED + zlib.crc32(request.node.nodeid.encode())
    reseed_random(seed)
    return seed


# A reply, or something that decides one from the request headers — which is what
# conditional GETs need, since the answer depends on If-None-Match.
Reply = tuple[int, bytes, Mapping[str, str]]
Route = Reply | Callable[[Mapping[str, str]], Reply]

# 304 and 204 must not carry a body, and some clients object to a Content-Length on
# one that doesn't.
BODYLESS = frozenset({204, 304})


def _handler(routes: Mapping[str, Route]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = routes.get(self.path)
            if route is None:
                self._reply(404, b"", {})
                return
            headers = {key.lower(): value for key, value in self.headers.items()}
            # isinstance rather than callable(): a union of tuple-or-callable only
            # narrows one way round for the type checker.
            status, body, extra = route if isinstance(route, tuple) else route(headers)
            self._reply(status, body, extra)

        def _reply(self, status: int, body: bytes, extra: Mapping[str, str]) -> None:
            self.send_response(status)
            for key, value in extra.items():
                self.send_header(key, value)
            if status in BODYLESS:
                self.end_headers()
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *_args: object) -> None:
            pass

    return Handler


@pytest.fixture
def http_server() -> Iterator[Callable[[Mapping[str, Route]], str]]:
    """Start a real loopback HTTP server and return its base URL."""
    running: list[ThreadingHTTPServer] = []

    def start(routes: Mapping[str, Route]) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(routes))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        running.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}"

    yield start

    for httpd in running:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(scope="session")
def page() -> Callable[[str], str]:
    """One of the checked-in real pages, as text."""

    def read(name: str) -> str:
        return (PAGES / name).read_text(errors="replace")

    return read
