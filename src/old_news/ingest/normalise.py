"""What counts as the same URL, and as the same content."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Campaign and click identifiers, including publisher-specific ones: the same article
# served through two feeds differs only by these.
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
    """A URL reduced to what identifies the article, syntactically. No redirects resolved."""
    cleaned = url.strip()
    if not cleaned:
        return ""

    # A malformed port raises here, as does a broken IPv6 literal in urlsplit.
    try:
        parts = urlsplit(cleaned)
        host = (parts.hostname or "").removeprefix("www.")
        port = parts.port
    except ValueError:
        return cleaned
    if not parts.netloc:
        return cleaned

    netloc = host
    if port and str(port) != DEFAULT_PORTS.get(parts.scheme.lower()):
        netloc = f"{host}:{port}"

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


def digest_fields(*fields: str) -> bytes:
    """A sha256 over fields kept apart by a separator, so their boundaries count."""
    digest = hashlib.sha256()
    for field in fields:
        digest.update(field.encode())
        digest.update(_FIELD_SEPARATOR)
    return digest.digest()


def content_fingerprint(*fields: str | None) -> bytes:
    """A digest over every field a publisher supplied, so a redacted byline still registers."""
    return digest_fields(*(normalise_text(field or "") for field in fields))
