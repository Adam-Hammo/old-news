"""The teaser a river row shows, cut from the markdown the archive stores."""

import re

IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\s]*\)")
LINK = re.compile(r"\[([^\]\n]*)\]\([^)\s]*\)")
# Headings, quotes and list bullets, which only mark a line when they open one.
LEADING = re.compile(r"^[ \t]{0,3}(?:[#>]+|[-*+]|\d+[.)])[ \t]*", re.MULTILINE)
# Only an opener that starts a word and a pair that wraps something, so `old_news` survives.
EMPHASIS = re.compile(r"(?<![\w*_`])(\*\*|__|\*|_|`)(?=\S)(.+?)(?<=\S)\1(?!\w)", re.DOTALL)
# A link the prefix taken in SQL cut through, in either half.
DANGLING = re.compile(r"!?\[[^\]\n]*(?:\]\([^)\s]*)?$")
SPACE = re.compile(r"\s+")

ELLIPSIS = "…"


def deck(markdown: str, limit: int) -> str:
    """Plain text, at most `limit` characters, ending on a word."""
    text = DANGLING.sub("", markdown)
    text = IMAGE.sub("", text)
    text = EMPHASIS.sub(r"\2", LINK.sub(r"\1", text))
    text = SPACE.sub(" ", LEADING.sub("", text)).strip()

    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + ELLIPSIS
