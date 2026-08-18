import os
import threading
from collections.abc import Callable, Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# Ryuk bind-mounts the docker socket, which Docker Desktop on macOS refuses.
# testcontainers reads its config at import, so this must run first.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

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

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


@pytest.fixture
def http_server() -> Iterator[Callable[[Mapping[str, Route]], str]]:
    """Start a real loopback HTTP server and return its base URL.

    `fetch/` is tested against a socket rather than a stubbed transport, which is
    how the redirect and 304 paths get exercised at all — so this is shared rather
    than rebuilt per test module.
    """
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
