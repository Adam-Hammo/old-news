"""The trafilatura boundary. Nothing else imports it. Markdown is the stored form.

lxml is pinned above trafilatura's floor: earlier releases do not declare free-thread
safety, and importing one re-enables the GIL for the whole worker.
"""

import dataclasses
import re
from importlib.metadata import version

import trafilatura

from old_news.db import ImageRole

EXTRACTOR = "trafilatura"

# Bumped when anything below changes what comes out, so old rows stay attributable.
RULES_REVISION = 1

# Not a markdown parser on purpose: a missed link costs a JSONB row, not correctness.
LINK = re.compile(r"\[([^\]\n]*)\]\((https?://[^)\s]+)\)")
IMAGE = re.compile(r"!\[([^\]\n]*)\]\((https?://[^)\s]+)\)")

PARAGRAPH_BREAK = "\n\n"


def extractor_version() -> str:
    return f"{version(EXTRACTOR)}+{RULES_REVISION}"


@dataclasses.dataclass(frozen=True, slots=True)
class Link:
    url: str
    anchor: str


@dataclasses.dataclass(frozen=True, slots=True)
class Image:
    url: str
    role: ImageRole
    alt: str


@dataclasses.dataclass(frozen=True, slots=True)
class Article:
    """What one extractor made of one page."""

    body: str = ""
    title: str = ""
    byline: str = ""
    language: str = ""
    site_name: str = ""
    page_type: str = ""
    published_claim: str = ""
    links: tuple[Link, ...] = ()
    images: tuple[Image, ...] = ()

    @property
    def char_count(self) -> int:
        return len(self.body)

    @property
    def paragraph_count(self) -> int:
        return len([block for block in self.body.split(PARAGRAPH_BREAK) if block.strip()])

    @property
    def link_density(self) -> float:
        """Characters inside link anchors as a share of the whole."""
        if not self.body:
            return 0.0
        anchored = sum(len(anchor) for anchor, _ in LINK.findall(self.body))
        return round(anchored / len(self.body), 4)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse(html: str, url: str) -> Article:
    """Pull a readable article out of a stored page, resolving links against `url`."""
    body = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_comments=False,
    )
    if not body:
        return Article()

    metadata = trafilatura.extract_metadata(html, default_url=url)
    claimed = metadata.as_dict() if metadata else {}

    images = [
        Image(url=lead, role=ImageRole.LEAD, alt="")
        for lead in [_text(claimed.get("image"))]
        if lead
    ]
    images += [
        Image(url=target, role=ImageRole.BODY, alt=alt)
        for alt, target in IMAGE.findall(body)
        if target != (images[0].url if images else None)
    ]

    return Article(
        body=body,
        title=_text(claimed.get("title")),
        byline=_text(claimed.get("author")),
        language=_text(claimed.get("language")),
        site_name=_text(claimed.get("sitename")),
        page_type=_text(claimed.get("pagetype")),
        published_claim=_text(claimed.get("date")),
        links=tuple(Link(url=target, anchor=anchor) for anchor, target in LINK.findall(body)),
        images=tuple(images),
    )


def parse_fragment(html: str, url: str) -> Article:
    """Pull a readable article out of what a feed already gave us.

    No metadata: with no `<head>` to read, `extract_metadata` returns the first heading.
    """
    body = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_comments=False,
    )
    if not body:
        return Article()

    return Article(
        body=body,
        links=tuple(Link(url=target, anchor=anchor) for anchor, target in LINK.findall(body)),
        images=tuple(
            Image(url=target, role=ImageRole.BODY, alt=alt) for alt, target in IMAGE.findall(body)
        ),
    )
