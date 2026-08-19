"""The robots.txt parser boundary. Nothing else imports it.

An absent or unreachable robots.txt is an empty body, which allows everything, so
callers never branch on whether a policy exists.

Protego rather than `urllib.robotparser`. The stdlib does handle wildcards and
longest-match precedence, but it normalises a rule pattern and the URL it matches
differently: `=` is percent-encoded in the pattern and left alone in the query, so
`Disallow: /*/*source=` never matches `?source=rss`.
"""

import dataclasses
from urllib.parse import urlsplit

from protego import Protego

# RFC 9309 §2.4. The stdlib parser implements this and protego does not, so it
# lives here: a host that bans everything has still published its own rules.
ALWAYS_ALLOWED = "/robots.txt"


@dataclasses.dataclass(frozen=True, slots=True)
class Rules:
    """One host's robots.txt, as it applies to one user agent.

    Records don't merge: a `*` block's rules don't apply to an agent with its own.
    """

    crawl_delay: float | None
    _rules: Protego
    _user_agent: str

    @property
    def blocks_everything(self) -> bool:
        """A blanket bot ban rather than a rule about anything in particular."""
        return not self.allows("/")

    def allows(self, url: str) -> bool:
        """Whether this agent may fetch a URL. Path and query are both matched —
        `Disallow: /*/*source=` is about a query string and nothing else."""
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
