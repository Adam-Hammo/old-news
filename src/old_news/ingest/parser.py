"""The feedparser boundary. Nothing else in the codebase imports feedparser."""

import datetime
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import feedparser

from old_news.ingest.normalise import canonical_url, digest_fields

# Bumped when anything below changes which text comes out of an entry, so a stored
# carving stays attributable to the rules that made it.
RULES_REVISION = 1

# <sy:updatePeriod> as seconds. <sy:updateFrequency> divides these.
UPDATE_PERIODS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
    "yearly": 31536000,
}


def parser_version() -> str:
    """What chose an item's text, stamped onto every feed capture."""
    return f"{feedparser.__version__}+{RULES_REVISION}"


@dataclass(frozen=True, slots=True)
class Identity:
    key: str
    source: str


@dataclass(frozen=True, slots=True)
class ParsedItem:
    guid: str = ""
    url: str = ""
    canonical_url: str = ""
    title: str = ""
    author: str = ""
    summary: str = ""
    content: str = ""
    comments_url: str = ""
    tags: tuple[str, ...] = ()
    enclosures: tuple[dict[str, str], ...] = ()
    published_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    @property
    def identity(self) -> Identity:
        """The key this article is recognised by, and which tier produced it."""
        if self.guid:
            return Identity(self.guid, "guid")
        if self.canonical_url:
            return Identity(self.canonical_url, "link")

        published = self.published_at.isoformat() if self.published_at else ""
        return Identity(digest_fields(self.title, published, self.summary).hex(), "hash")


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    title: str = ""
    description: str = ""
    site_url: str = ""
    language: str = ""
    icon_url: str = ""
    platform: str = ""
    hub_url: str = ""
    ttl_seconds: int | None = None
    categories: tuple[str, ...] = ()
    items: tuple[ParsedItem, ...] = ()
    ok: bool = True
    note: str = ""

    @property
    def empty(self) -> bool:
        """Nothing usable came out, whatever the parser thought of the syntax."""
        return not self.items and not self.title


def _timestamp(value: time.struct_time | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime(*value[:6], tzinfo=datetime.UTC)
    except TypeError, ValueError:
        return None


def _resolve(base: str, href: str) -> str:
    """Absolutise a link, or keep it as published when it will not parse."""
    try:
        return urljoin(base, href)
    except ValueError:
        return href


def _terms(entries: list[Any] | None) -> tuple[str, ...]:
    return tuple(
        sorted({stripped for tag in entries or [] if (stripped := (tag.get("term") or "").strip())})
    )


def _body(entry: Any) -> str:
    """Prefer full content over the summary, and the richest type on offer."""
    contents = entry.get("content") or []
    html = [
        c.get("value", "")
        for c in contents
        if c.get("type") in {"text/html", "application/xhtml+xml"}
    ]
    if html:
        return max(html, key=len)
    if contents:
        return max((c.get("value", "") for c in contents), key=len)
    return entry.get("summary", "") or ""


def _enclosures(entry: Any, base: str) -> tuple[dict[str, str], ...]:
    found = []
    for enclosure in entry.get("enclosures") or []:
        href = enclosure.get("href") or enclosure.get("url") or ""
        if not href:
            continue
        found.append(
            {
                "url": _resolve(base, href),
                "type": enclosure.get("type") or "",
                "length": str(enclosure.get("length") or ""),
            }
        )
    return tuple(found)


def _ttl_seconds(feed: Any) -> int | None:
    """A publisher asking to be polled less often. Minutes, per the RSS spec."""
    ttl = feed.get("ttl")
    if ttl:
        try:
            return max(int(ttl), 0) * 60
        except TypeError, ValueError:
            pass

    period = UPDATE_PERIODS.get(str(feed.get("sy_updateperiod", "")).strip().lower())
    if not period:
        return None
    try:
        frequency = max(int(feed.get("sy_updatefrequency", 1)), 1)
    except TypeError, ValueError:
        frequency = 1
    return period // frequency


def _hub(feed: Any) -> str:
    for link in feed.get("links") or []:
        if link.get("rel") == "hub" and link.get("href"):
            return str(link["href"])
    return ""


def _guid(entry: Any) -> str:
    return str(entry.get("id") or entry.get("guid") or "").strip()


def _present(entry: Any, key: str) -> Any:
    """Read a key only if it is really there.

    FeedParserDict maps `updated_parsed` onto `published_parsed` when the former is
    missing, and the two mean different things.
    """
    return entry[key] if key in entry else None  # noqa: SIM401 — .get() triggers the fallback


def parse(body: bytes, *, url: str) -> ParsedFeed:
    """Parse a feed document. `bozo` is recorded rather than treated as failure."""
    parsed = feedparser.parse(body)
    feed = parsed.get("feed") or {}

    note = ""
    if parsed.get("bozo"):
        note = str(parsed.get("bozo_exception") or "")[:500]

    base = str(feed.get("link") or url)

    items = []
    for entry in parsed.get("entries") or []:
        link = _resolve(base, raw_link) if (raw_link := entry.get("link")) else ""
        items.append(
            ParsedItem(
                guid=_guid(entry),
                url=link,
                canonical_url=canonical_url(link),
                title=(entry.get("title") or "").strip(),
                author=(entry.get("author") or "").strip(),
                summary=entry.get("summary", "") or "",
                content=_body(entry),
                comments_url=_resolve(base, raw) if (raw := entry.get("comments")) else "",
                tags=_terms(entry.get("tags")),
                enclosures=_enclosures(entry, base),
                published_at=_timestamp(_present(entry, "published_parsed")),
                updated_at=_timestamp(_present(entry, "updated_parsed")),
            )
        )

    image = feed.get("image") or {}
    return ParsedFeed(
        title=(feed.get("title") or "").strip(),
        description=(feed.get("subtitle") or feed.get("description") or "").strip(),
        site_url=str(feed.get("link") or ""),
        language=(feed.get("language") or "")[:32],
        icon_url=str(feed.get("icon") or image.get("href") or ""),
        platform=(feed.get("generator") or "").strip(),
        hub_url=_hub(feed),
        ttl_seconds=_ttl_seconds(feed),
        categories=_terms(feed.get("tags")),
        items=tuple(items),
        ok=not parsed.get("bozo") or bool(items),
        note=note,
    )
