from pydantic import BaseModel


class IngestSettings(BaseModel):
    # How often a healthy feed is polled, and the bounds the policy moves within.
    default_interval_seconds: int = 30 * 60
    min_interval_seconds: int = 5 * 60
    max_interval_seconds: int = 24 * 60 * 60

    # Failure backoff: interval * (factor ** consecutive_failures), capped at max.
    backoff_factor: float = 2.0
    max_consecutive_failures: int = 10

    # A feed that publishes gets polled sooner, one that never does drifts later.
    busy_interval_multiplier: float = 0.5
    idle_interval_multiplier: float = 1.5

    # Feeds claimed per scheduler tick. Bounds a thundering herd after downtime.
    poll_batch_size: int = 50

    # A feed's own <ttl>/sy:updatePeriod is a hint, honoured as a floor only —
    # publishers use it to ask for less traffic, not more.
    honour_feed_ttl: bool = True
