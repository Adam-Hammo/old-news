"""Which requests count as going to the same place."""

from old_news.fetch import http_url

LOCK_PREFIX = "host"


def host_of(url: str) -> str:
    """The politeness group a URL belongs to, or "" if it isn't fetchable.

    Host, not registrable domain: splitting `theguardian.com` from `co.uk` needs a
    public-suffix list, and a connection is per host anyway.
    """
    parsed = http_url(url)
    if parsed is None:
        return ""
    return (parsed.host or "").removeprefix("www.")


def host_lock(host: str) -> str | None:
    """The job lock Postgres serialises on. None for a hostless, unfetchable URL."""
    return f"{LOCK_PREFIX}:{host}" if host else None


def with_www(url: str) -> str:
    """The same URL under the `www.` name, unchanged if it is already there.

    `host_of` strips the prefix because it is not a different publisher. Which of the
    two names carries a DNS record is a separate question, and not always the apex.
    """
    parsed = http_url(url)
    if parsed is None or not parsed.host or parsed.host.startswith("www."):
        return url
    return url.replace(parsed.host, f"www.{parsed.host}", 1)
