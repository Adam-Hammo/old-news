"""The markdown-it boundary. Extraction output is markdown; a page wants HTML."""

import html
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token

# Roughly 230 words a minute at 5.7 characters a word, which is what a subject line
# is claiming when it says how long an issue is.
CHARS_PER_MINUTE = 1310

TEASER_CHARS = 220


def _image_rule(images: Mapping[str, str]):
    """Point an image at the copy in the book, or drop it — a missing one is a grey box."""

    def render(tokens: Sequence[Token], idx: int, _options: Any, _env: Any) -> str:
        token = tokens[idx]
        local = images.get(token.attrGet("src") or "")
        if not local:
            return ""
        alt = html.escape(token.content or "", quote=True)
        return f'<img src="{html.escape(local, quote=True)}" alt="{alt}"/>'

    return render


def to_html(body: str, images: Mapping[str, str]) -> str:
    """Render one reading. Raw HTML is escaped rather than passed, so the output is ours."""
    parser = MarkdownIt("commonmark", {"html": False, "breaks": False, "typographer": True})
    # `renderer` is typed as the protocol, which does not declare the rule table.
    cast(RendererHTML, parser.renderer).rules["image"] = _image_rule(images)
    # A dropped image leaves the paragraph that held it behind.
    return re.sub(r"<p>\s*</p>\s*", "", parser.render(body))


def _same(left: str, right: str) -> bool:
    return (
        re.sub(r"\W+", " ", left).strip().casefold()
        == re.sub(r"\W+", " ", right).strip().casefold()
    )


def without_title(body: str, title: str) -> str:
    """Drop the headline the extractor kept, so the page does not carry it twice."""
    lines = body.lstrip().split("\n")
    heading = re.match(r"#{1,3}\s+(.*)", lines[0]) if lines else None
    if heading and _same(heading.group(1), title):
        return "\n".join(lines[1:]).lstrip()
    return body


def byline(*parts: str) -> str:
    """The parts that say something. Plenty of feeds put the outlet in the author field."""
    kept: list[str] = []
    for part in parts:
        if part and not any(_same(part, already) for already in kept):
            kept.append(part)
    return " · ".join(kept)


def minutes(chars: int) -> int:
    return max(1, round(chars / CHARS_PER_MINUTE))


def teaser(body: str) -> str:
    """A line of the article for the table of contents, with the markup taken out."""
    flat = re.sub(r"^[-*+#>\s]+", " ", body, flags=re.MULTILINE)
    # The URL stops at the closing bracket, or a greedy \S+ eats it and the sentence's
    # punctuation along with it.
    flat = re.sub(r"[#>*_`\[\]()!]|https?://[^\s)]+", " ", flat)
    flat = re.sub(r"\s+", " ", flat).strip()
    if len(flat) <= TEASER_CHARS:
        return flat
    return flat[:TEASER_CHARS].rsplit(" ", 1)[0] + "…"


def page(
    *, title: str, outlet: str, author: str, dateline: str, url: str, lead: str, body: str
) -> str:
    """One article as a file the converter reads. Authored here, so nothing needs cleaning up."""
    credit = byline(outlet, author, dateline)
    hero = ""
    if lead:
        hero = f'<p class="lead"><img src="{html.escape(lead, quote=True)}" alt=""/></p>'
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"/>'
        f"<title>{html.escape(title)}</title></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="byline">{html.escape(credit)}</p>'
        f"{hero}"
        f'<div class="body">{body}</div>'
        f'<p class="source"><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></p>'
        "</body></html>"
    )
