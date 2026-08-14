"""OPML import and export — how feeds get in, and the guarantee they can get out."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.sax.saxutils import escape, quoteattr

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as defused_fromstring

# The size cap bounds the input; defusedxml bounds what a small input can expand
# to. A 1 KB file with nested entities is the attack, so the cap alone is no
# defence.
MAX_BYTES = 8 * 1024 * 1024


class OpmlError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Outline:
    """One subscription."""

    url: str
    title: str = ""
    category: str = ""
    site_url: str = ""

    # `url` is an htmlUrl, not an xmlUrl — the file named a site, not a feed.
    needs_discovery: bool = False


def parse(data: bytes) -> list[Outline]:
    if len(data) > MAX_BYTES:
        raise OpmlError(f"OPML larger than {MAX_BYTES} bytes")

    try:
        root = defused_fromstring(data)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise OpmlError(str(exc)) from exc

    body = root.find("body")
    if body is None:
        raise OpmlError("OPML has no <body>")

    outlines: list[Outline] = []
    _walk(body, category="", into=outlines)
    return outlines


def _walk(element: ET.Element, *, category: str, into: list[Outline]) -> None:
    for child in element.findall("outline"):
        feed_url = (child.get("xmlUrl") or child.get("xmlurl") or "").strip()
        site_url = (child.get("htmlUrl") or "").strip()
        title = (child.get("title") or child.get("text") or "").strip()

        if feed_url:
            into.append(Outline(url=feed_url, title=title, category=category, site_url=site_url))
            continue

        nested = child.findall("outline")
        if nested:
            # A container. Its title is the category for everything beneath it,
            # flattened — a tree is a read-surface concern.
            _walk(child, category=title or category, into=into)
        elif site_url:
            # A leaf naming a site rather than a feed. Exporters do this, and
            # throwing it away loses a subscription.
            into.append(Outline(url=site_url, title=title, category=category, needs_discovery=True))


def render(outlines: list[Outline], *, title: str = "old-news") -> bytes:
    """Regenerate an OPML file. Grouped by category, so a round trip is stable."""
    grouped: dict[str, list[Outline]] = {}
    for outline in outlines:
        grouped.setdefault(outline.category, []).append(outline)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "  <head>",
        f"    <title>{escape(title)}</title>",
        f"    <dateCreated>{datetime.now(UTC).strftime('%a, %d %b %Y %H:%M:%S %z')}</dateCreated>",
        "  </head>",
        "  <body>",
    ]

    for category in sorted(grouped):
        indent = "    "
        if category:
            lines.append(f"    <outline text={quoteattr(category)} title={quoteattr(category)}>")
            indent = "      "
        for outline in sorted(grouped[category], key=lambda o: (o.title.lower(), o.url)):
            attributes = [
                f"text={quoteattr(outline.title or outline.url)}",
                f"title={quoteattr(outline.title or outline.url)}",
                'type="rss"',
                f"xmlUrl={quoteattr(outline.url)}",
            ]
            if outline.site_url:
                attributes.append(f"htmlUrl={quoteattr(outline.site_url)}")
            lines.append(f"{indent}<outline {' '.join(attributes)}/>")
        if category:
            lines.append("    </outline>")

    lines += ["  </body>", "</opml>", ""]
    return "\n".join(lines).encode()
