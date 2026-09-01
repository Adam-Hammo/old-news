"""The trafilatura boundary. Nothing else imports it. Markdown is the stored form.

lxml is pinned above trafilatura's floor: earlier releases do not declare free-thread
safety, and importing one re-enables the GIL for the whole worker.
"""

import dataclasses
import re
from importlib.metadata import version
from urllib.parse import urljoin

import trafilatura
from lxml.etree import LxmlError
from lxml.html import HtmlElement, HTMLParser, fromstring

from old_news.db import ImageRole

EXTRACTOR = "trafilatura"

# Bumped when anything below changes what comes out, so old rows stay attributable.
RULES_REVISION = 2

# Not a markdown parser on purpose: a missed link costs a JSONB row, not correctness.
LINK = re.compile(r"\[([^\]\n]*)\]\((https?://[^)\s]+)\)")
IMAGE = re.compile(r"!\[([^\]\n]*)\]\((https?://[^)\s]+)")
# What a reading kept beyond a wall of prose, counted where it opens a line.
STRUCTURE = re.compile(r"^(?:#{1,6} |> |!\[)", re.MULTILINE)
SPACE = re.compile(r"\s+")

PARAGRAPH_BREAK = "\n\n"
QUOTE_MARK = "> "

# Matched to the parser trafilatura loads a string with, because it is handed the tree
# this one built: its heading pass retags a node's children, and raises on a comment.
PARSER = HTMLParser(collect_ids=False, remove_comments=True, remove_pis=True)


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
    def structure_count(self) -> int:
        """Headings, quotes and images — the furniture a teaser tends to strip."""
        return len(STRUCTURE.findall(self.body))

    @property
    def link_density(self) -> float:
        """Characters inside link anchors as a share of the whole."""
        if not self.body:
            return 0.0
        anchored = sum(len(anchor) for anchor, _ in LINK.findall(self.body))
        return round(anchored / len(self.body), 4)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _tree(html: str) -> HtmlElement | None:
    """The document as lxml sees it, or None when there is nothing to parse."""
    try:
        return fromstring(html, parser=PARSER)
    except LxmlError, ValueError:
        return None


def _mark_quotes(tree: HtmlElement) -> HtmlElement:
    """Open every quoted block with the mark trafilatura's markdown leaves off."""
    # On the way in, so trafilatura still decides what is content and only the mark has
    # to survive it. Nested quotes stack: the outer pass reaches the inner blocks first.
    for quote in tree.iter("blockquote"):
        for block in quote.findall(".//p") or [quote]:
            block.text = QUOTE_MARK + (block.text or "")
    return tree


def _markdown(tree: HtmlElement, url: str) -> str:
    return (
        trafilatura.extract(
            _mark_quotes(tree),
            url=url,
            output_format="markdown",
            include_links=True,
            include_images=True,
            include_comments=False,
        )
        or ""
    )


def _picture(image: HtmlElement, url: str) -> str:
    """One image as markdown, carrying whatever the publisher hung off it."""
    source = urljoin(url, _text(image.get("src")))
    # The joke in a comic and the caption in a photo blog both live in `title`.
    title = _text(image.get("title")).replace("\\", "").replace('"', "'")
    hover = f' "{title}"' if title else ""
    return f"![{_text(image.get('alt'))}]({source}{hover})"


def _salvage(html: str, url: str) -> str:
    """A feed fragment taken at face value: the items that are a picture and a caption."""
    # A fragment is the publisher's own payload, not a page to find an article inside.
    # Trafilatura wants prose and gives a comic nothing, which reads as a failed fetch.
    # Parsed again because trafilatura prunes the tree it is handed.
    tree = _tree(html)
    if tree is None:
        return ""
    blocks = [_picture(image, url) for image in tree.iter("img") if _text(image.get("src"))]
    caption = SPACE.sub(" ", tree.text_content()).strip()
    return PARAGRAPH_BREAK.join(blocks + ([caption] if caption else []))


def _found(body: str, url: str) -> tuple[tuple[Link, ...], tuple[Image, ...]]:
    """The links and body images a reading points at, resolved against `url`."""
    return (
        tuple(Link(url=target, anchor=anchor) for anchor, target in LINK.findall(body)),
        tuple(
            Image(url=target, role=ImageRole.BODY, alt=alt) for alt, target in IMAGE.findall(body)
        ),
    )


def parse(html: str, url: str) -> Article:
    """Pull a readable article out of a stored page, resolving links against `url`."""
    tree = _tree(html)
    if tree is None:
        return Article()

    body = _markdown(tree, url)
    if not body:
        return Article()

    metadata = trafilatura.extract_metadata(html, default_url=url)
    claimed = metadata.as_dict() if metadata else {}

    links, found = _found(body, url)
    lead = [
        Image(url=claimed_lead, role=ImageRole.LEAD, alt="")
        for claimed_lead in [_text(claimed.get("image"))]
        if claimed_lead
    ]
    images = lead + [image for image in found if not lead or image.url != lead[0].url]

    return Article(
        body=body,
        title=_text(claimed.get("title")),
        byline=_text(claimed.get("author")),
        language=_text(claimed.get("language")),
        site_name=_text(claimed.get("sitename")),
        page_type=_text(claimed.get("pagetype")),
        published_claim=_text(claimed.get("date")),
        links=links,
        images=tuple(images),
    )


def parse_fragment(html: str, url: str) -> Article:
    """Pull a readable article out of what a feed already gave us.

    No metadata: with no `<head>` to read, `extract_metadata` returns the first heading.
    """
    tree = _tree(html)
    if tree is None:
        return Article()

    body = _markdown(tree, url) or _salvage(html, url)
    if not body:
        return Article()

    links, images = _found(body, url)
    return Article(body=body, links=links, images=images)
