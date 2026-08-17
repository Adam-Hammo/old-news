from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2

from old_news.config.http import HttpSettings
from old_news.observability import instrument_http_client, span


class FetchError(Exception):
    """Transport failed. HTTP error statuses are not errors — they come back as a response."""


class Timeout(FetchError):
    pass


class TooLarge(FetchError):
    pass


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
    ) -> Response:
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        # Only scheme/host/path — a feed URL's query string can carry an API key,
        # and span attributes are not scrubbed once they leave here.
        target = httpx2.URL(url).copy_with(query=None, fragment=None)

        attributes: dict[str, Any] = {
            "http.request.method": "GET",
            "url.redacted": str(target),
            "http.conditional": bool(headers),
        }
        with span("GET feed", **attributes) as current:
            try:
                async with self._client.stream("GET", url, headers=headers) as response:
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
                raise FetchError(str(exc)) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
