"""A reading as plain text, for the screens that show a fragment of one rather than all of it."""

import html
import re


def flatten(body: str) -> str:
    """Markdown as one line of prose. Not a renderer: nothing here has to round-trip."""
    # Entities first: `&#x27;` is an apostrophe, and stripping the `#` off it leaves litter.
    stripped = re.sub(r"^[-*+#>\s]+", " ", html.unescape(body), flags=re.MULTILINE)
    # The URL stops at the closing bracket, or a greedy \S+ eats it and the sentence's
    # punctuation along with it.
    stripped = re.sub(r"[#>*_`\[\]()!]|https?://[^\s)]+", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def clipped(text: str, chars: int) -> str:
    """Cut on a word, and say that it was cut."""
    if len(text) <= chars:
        return text
    return text[:chars].rsplit(" ", 1)[0] + "…"
