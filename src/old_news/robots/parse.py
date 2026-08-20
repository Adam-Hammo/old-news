"""The robots.txt parser boundary. Nothing else imports it. An empty body allows everything.

Protego because the stdlib percent-encodes `=` in a rule pattern and not in the query it
matches, so a rule carrying one silently never fires.
"""

import dataclasses
from urllib.parse import urlsplit

from protego import Protego

# RFC 9309 §2.4, which protego does not implement.
ALWAYS_ALLOWED = "/robots.txt"


@dataclasses.dataclass(frozen=True, slots=True)
class Rules:
    """One host's robots.txt, as it applies to one user agent. Records do not merge."""

    crawl_delay: float | None
    _rules: Protego
    _user_agent: str

    @property
    def blocks_everything(self) -> bool:
        """A blanket bot ban rather than a rule about anything in particular."""
        return not self.allows("/")

    def allows(self, url: str) -> bool:
        """Whether this agent may fetch a URL. Path and query are both matched."""
        if urlsplit(url).path == ALWAYS_ALLOWED:
            return True
        return self._rules.can_fetch(url, self._user_agent)


def parse(body: str, *, user_agent: str, max_crawl_delay: float | None = None) -> Rules:
    """Read a robots.txt body into the answers it gives one agent."""
    rules = Protego.parse(body)

    delay = rules.crawl_delay(user_agent)
    crawl_delay = float(delay) if delay is not None else None
    if crawl_delay is not None and max_crawl_delay is not None:
        crawl_delay = min(crawl_delay, max_crawl_delay)

    return Rules(crawl_delay=crawl_delay, _rules=rules, _user_agent=user_agent)


def allow_everything(user_agent: str) -> Rules:
    """What an absent, empty or unreachable robots.txt means."""
    return parse("", user_agent=user_agent)
