from pydantic import BaseModel


class RobotsSettings(BaseModel):
    """Which agent we are lives in `HttpSettings.user_agent`, not here."""

    # How long a stored answer is trusted. A day is what the big crawlers use.
    ttl_seconds: int = 24 * 60 * 60
    # A host that couldn't be reached is retried sooner than one that answered.
    failure_ttl_seconds: int = 60 * 60

    # Google stops reading at 500 KiB and so do we; nothing past it is a rule.
    max_body_bytes: int = 512 * 1024

    # A publisher asking for an hour between requests would push a batch of its
    # feeds days into the future. Honour the request, but not unboundedly.
    max_crawl_delay_seconds: float = 120.0

    # Hosts refreshed per sweep. Bounds the work when a big import lands.
    refresh_batch_size: int = 50
