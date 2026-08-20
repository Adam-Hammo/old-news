"""How far apart two requests to one host are allowed to be. Pure; Postgres serialises."""

from collections import Counter
from collections.abc import Iterable, Mapping


def gap_for(host: str, *, minimum: float, crawl_delays: Mapping[str, float]) -> float:
    """Our gap or the host's own `Crawl-delay`, whichever is longer."""
    return max(minimum, crawl_delays.get(host, 0.0))


def stagger(
    hosts: Iterable[str], *, minimum: float, crawl_delays: Mapping[str, float] | None = None
) -> list[float]:
    """How long to hold each job back, by its position within its own host."""
    delays = crawl_delays or {}
    position: Counter[str] = Counter()
    held = []
    for host in hosts:
        held.append(position[host] * gap_for(host, minimum=minimum, crawl_delays=delays))
        position[host] += 1
    return held
