from pydantic import BaseModel


class IngestSettings(BaseModel):
    # How often a healthy feed is polled, and the bounds the policy moves within. The
    # ceiling is what a quiet feed drifts to, so it is also the longest anything goes
    # unseen: at a day, a feed that had been quiet for a while published in the morning
    # and turned up in the evening.
    default_interval_seconds: int = 15 * 60
    min_interval_seconds: int = 5 * 60
    max_interval_seconds: int = 6 * 60 * 60

    # Failure backoff: interval * (factor ** consecutive_failures), on its own ceiling.
    # How long a quiet feed may go unseen and how long a publisher gets to be down are
    # different questions, and sharing one number meant polling faster gave up sooner.
    backoff_factor: float = 2.0
    max_backoff_seconds: int = 24 * 60 * 60
    max_consecutive_failures: int = 10

    # A feed that publishes gets polled sooner, one that never does drifts later. The
    # drift compounds, so a gentle one is a long way from the ceiling either way.
    busy_interval_multiplier: float = 0.5
    idle_interval_multiplier: float = 1.25

    # Feeds claimed per scheduler tick. Bounds a thundering herd after downtime.
    poll_batch_size: int = 50

    # A feed's own <ttl>/sy:updatePeriod is a hint, honoured as a floor only —
    # publishers use it to ask for less traffic, not more.
    honour_feed_ttl: bool = True
