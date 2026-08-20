"""Which requests count as going to the same place."""

from urllib.parse import urlsplit, urlunsplit

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

    Rebuilt through `urlsplit`, not a string replace: the parsed host is lowercased and
    punycoded, so replacing it finds nothing in `EXAMPLE.com` or any IDN host.
    """
    if http_url(url) is None:
        return url
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.hostname.startswith("www."):
        return url
    # Splitting on the last `@` keeps any userinfo where it was.
    at = parsed.netloc.rfind("@")
    userinfo, host_port = parsed.netloc[: at + 1], parsed.netloc[at + 1 :]
    return urlunsplit(parsed._replace(netloc=f"{userinfo}www.{host_port}"))
