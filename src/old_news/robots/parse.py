"""The `urllib.robotparser` boundary. Nothing else imports it.

An absent or unreachable robots.txt is an empty body, which allows everything, so
callers never branch on whether a policy exists.
"""

import dataclasses
import urllib.robotparser
from urllib.parse import urlsplit


@dataclasses.dataclass(frozen=True, slots=True)
class Rules:
    """One host's robots.txt, as it applies to one user agent.

    Records don't merge: a `*` block's rules don't apply to an agent with its own.
    """

    crawl_delay: float | None
    _parser: urllib.robotparser.RobotFileParser
    _user_agent: str

    @property
    def blocks_everything(self) -> bool:
        """A blanket bot ban rather than a rule about anything in particular."""
        return not self.allows("/")

    def allows(self, url: str) -> bool:
        """Whether this agent may fetch a URL. Only path and query are matched."""
        target = urlsplit(url)
        path = target.path or "/"
        if target.query:
            path = f"{path}?{target.query}"
        return self._parser.can_fetch(self._user_agent, path)


def parse(body: str, *, user_agent: str, max_crawl_delay: float | None = None) -> Rules:
    """Read a robots.txt body into the answers it gives one agent."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.splitlines())
    # Without an mtime the stdlib calls every question unanswerable: can_fetch says
    # no to everything and crawl_delay says None.
    parser.modified()

    delay = parser.crawl_delay(user_agent)
    crawl_delay = float(delay) if delay is not None else None
    if crawl_delay is not None and max_crawl_delay is not None:
        crawl_delay = min(crawl_delay, max_crawl_delay)

    return Rules(crawl_delay=crawl_delay, _parser=parser, _user_agent=user_agent)


def allow_everything(user_agent: str) -> Rules:
    """What an absent, empty or unreachable robots.txt means."""
    return parse("", user_agent=user_agent)
