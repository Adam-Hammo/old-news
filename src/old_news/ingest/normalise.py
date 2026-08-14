"""What counts as the same URL, and as the same content.

Both answers are provisional. The corpus is what tells us whether they are right —
how many "edits" turn out to be rotating ad markup, and how many cross-feed
duplicates a canonical URL actually catches.
"""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Campaign and click identifiers. Publisher-specific ones are here because they
# appear on the same article served through different feeds, which is exactly
# the case cross-source dedup has to see through.
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "matomo_", "piwik_", "hsa_")
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "twclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "cmp",
        "smid",
        "at_medium",
        "at_campaign",
        "at_custom1",
        "at_custom2",
        "at_custom3",
        "at_custom4",
        "ncid",
        "sh",
    }
)

DEFAULT_PORTS = {"http": "80", "https": "443"}

_WHITESPACE = re.compile(r"\s+")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_FIELD_SEPARATOR = b"\x1f"


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def canonical_url(url: str) -> str:
    """A URL reduced to what identifies the article, syntactically only.

    Resolving redirects would need a network fetch, so a FeedBurner proxy link
    and the article it points at stay different here. That arrives with extract/.
    """
    if not url or not url.strip():
        return ""

    parts = urlsplit(url.strip())
    if not parts.netloc:
        return url.strip()

    host = parts.hostname or ""
    host = host.removeprefix("www.")

    netloc = host
    if parts.port and str(parts.port) != DEFAULT_PORTS.get(parts.scheme.lower()):
        netloc = f"{host}:{parts.port}"

    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )

    path = parts.path.rstrip("/") or "/"

    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(kept), ""))


def normalise_text(value: str) -> str:
    """Collapse the differences that are not edits."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", _HTML_COMMENT.sub("", value)).strip()


def content_fingerprint(*fields: str | None) -> bytes:
    """A digest over every field a publisher supplied.

    Every field, deliberately: hashing only title and body is how a redacted
    byline or a quietly changed URL goes unrecorded.
    """
    digest = hashlib.sha256()
    for field in fields:
        digest.update(normalise_text(field or "").encode())
        digest.update(_FIELD_SEPARATOR)
    return digest.digest()
