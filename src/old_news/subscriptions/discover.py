"""Given a site URL, find its feed."""

import re
from urllib.parse import urljoin

from old_news.fetch import Fetcher, FetchError

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")

_LINK = re.compile(rb"<link\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(rb"""(\w[\w:-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def _attributes(tag: bytes) -> dict[str, str]:
    found = {}
    for name, value in _ATTR.findall(tag):
        found[name.decode(errors="replace").lower()] = (
            value.strip(b"\"'").decode(errors="replace").strip()
        )
    return found


def feeds_in(html: bytes, *, base_url: str) -> list[str]:
    """Every <link rel="alternate"> pointing at a feed, in document order."""
    found: list[str] = []
    for tag in _LINK.findall(html):
        attributes = _attributes(tag)
        rels = attributes.get("rel", "").lower().split()
        if "alternate" not in rels:
            continue
        if attributes.get("type", "").lower() not in FEED_TYPES:
            continue
        href = attributes.get("href")
        if href:
            resolved = urljoin(base_url, href)
            if resolved not in found:
                found.append(resolved)
    return found


async def discover(url: str, fetcher: Fetcher) -> str | None:
    """The feed URL for a page, or the page itself if it is already a feed."""
    try:
        response = await fetcher.get(url)
    except FetchError:
        return None

    if not response.ok:
        return None

    content_type = (response.header("content-type") or "").split(";")[0].strip().lower()
    if content_type in FEED_TYPES or content_type in {"text/xml", "application/xml"}:
        return response.url

    candidates = feeds_in(response.body, base_url=response.url)
    return candidates[0] if candidates else None
