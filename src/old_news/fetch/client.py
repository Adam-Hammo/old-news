import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from old_news.config.http import HttpSettings
from old_news.observability import instrument_http_client, span

_HTTP_URL = TypeAdapter(AnyHttpUrl)


def http_url(url: str) -> AnyHttpUrl | None:
    """Parse a URL, or None if it isn't one we could fetch. Pydantic, so an IDN host punycodes."""
    try:
        return _HTTP_URL.validate_python(url.strip())
    except ValidationError:
        return None


def fetchable(url: str) -> bool:
    """Whether there is anything to fetch here."""
    return http_url(url) is not None


class FetchError(Exception):
    """Transport failed. An HTTP error status is not this; it comes back as a response."""


class Timeout(FetchError):
    pass


class TooLarge(FetchError):
    pass


class WrongContentType(FetchError):
    """Not what was asked for. Raised before the body is read, so nothing is downloaded."""


class Unresolvable(FetchError):
    """The host has no address at all, which is often a missing apex rather than a dead site."""


def _unresolvable(exc: BaseException) -> bool:
    """Whether a transport failure was DNS."""
    seen: BaseException | None = exc
    for _ in range(8):
        if seen is None:
            return False
        if isinstance(seen, socket.gaierror):
            return True
        nested = seen.args[0] if seen.args and isinstance(seen.args[0], BaseException) else None
        seen = seen.__cause__ or nested
    return False


# Not "GET": that is what the httpx2 instrumentation names its own span, and two spans
# sharing a name leave the redaction tests unable to tell them apart.
SPAN_NAME = "fetch"


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    url: str
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def etag(self) -> str | None:
        return self.header("etag")

    @property
    def last_modified(self) -> str | None:
        return self.header("last-modified")

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        return next((v for k, v in self.headers.items() if k.lower() == wanted), None)


class Fetcher:
    def __init__(self, settings: HttpSettings) -> None:
        self._max_body_bytes = settings.max_body_bytes
        self._client = httpx2.AsyncClient(
            headers={"User-Agent": settings.user_agent},
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            max_redirects=settings.max_redirects,
        )
        instrument_http_client(self._client)

    async def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: tuple[str, ...] | None = None,
    ) -> Response:
        """`accept` refuses a body by its declared type before any of it is read."""
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        # No query string: it can carry an API key, and attributes leave unscrubbed.
        target = httpx2.URL(url).copy_with(query=None, fragment=None)

        attributes: dict[str, Any] = {
            "http.request.method": "GET",
            "url.redacted": str(target),
            "http.conditional": bool(headers),
        }
        with span(SPAN_NAME, **attributes) as current:
            try:
                async with self._client.stream("GET", url, headers=headers) as response:
                    if accept is not None and response.status_code < 300:
                        declared = response.headers.get("content-type", "")
                        # Split on `;` for the charset, which is not part of the type.
                        kind = declared.split(";")[0].strip().lower()
                        if kind not in accept:
                            raise WrongContentType(f"{target} served {kind or 'no type'}")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_body_bytes:
                            raise TooLarge(f"{target} exceeded {self._max_body_bytes} bytes")

                    current.set_attribute("http.response.status_code", response.status_code)
                    current.set_attribute("http.response.body.size", len(body))
                    return Response(
                        status=response.status_code,
                        url=str(response.url),
                        body=bytes(body),
                        headers=dict(response.headers),
                    )
            except httpx2.TimeoutException as exc:
                current.record_exception(exc)
                raise Timeout(str(exc)) from exc
            except httpx2.HTTPError as exc:
                current.record_exception(exc)
                if _unresolvable(exc):
                    raise Unresolvable(str(exc)) from exc
                raise FetchError(str(exc)) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
