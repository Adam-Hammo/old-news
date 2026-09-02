"""What every scheduling sweep does: one job per due row, and at most one of them waiting."""

from collections.abc import Sequence
from typing import Any

from old_news import politeness, robots
from old_news.tasks.tracing import defer_unless_queued


async def defer_each(
    registered_task: Any,
    keys: Sequence[object],
    *,
    kwarg: str,
    lock_prefix: str,
    hosts: Sequence[str] = (),
    min_host_interval_seconds: float = 0.0,
) -> int:
    """Defer one job per key, skipping the ones already queued. How many went out."""
    # No hosts to be polite about: "" takes no lock and spaces nothing.
    visiting = hosts or [""] * len(keys)
    delays = politeness.stagger(
        visiting,
        minimum=min_host_interval_seconds,
        # Whatever these hosts asked for in robots.txt, honoured as a longer gap.
        crawl_delays=await robots.crawl_delays(visiting),
    )

    deferred = 0
    for key, host, delay in zip(keys, visiting, delays, strict=True):
        deferred += await defer_unless_queued(
            registered_task.configure(
                # One job per subject in flight, or a slow host lets them stack up.
                queueing_lock=f"{lock_prefix}:{key}",
                # Postgres hands out one job per host at a time, so nothing here keeps state.
                lock=politeness.host_lock(host),
                schedule_in={"seconds": delay} if delay else None,
            ),
            **{kwarg: str(key)},
        )
    return deferred
