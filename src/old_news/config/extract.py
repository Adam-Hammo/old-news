from pydantic import BaseModel, Field

from old_news.config.retry import RetrySettings


class ExtractSettings(BaseModel):
    # How long a version must have been the head before its page is worth fetching.
    # The first version of an item is captured regardless.
    settle_seconds: int = 60 * 60

    max_versions_per_item: int = 5

    capture_content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml")

    capture_batch_size: int = 25

    min_body_chars: int = 500
    min_paragraphs: int = 3

    extract_batch_size: int = 25

    image_content_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/avif",
        "image/gif",
    )
    image_batch_size: int = 25

    # The only form kept of an image, so it answers to both the archive and the phone.
    image_max_width: int = 1600
    image_quality: int = 65
    encode_batch_size: int = 25

    # Steeper and shorter-lived than a feed's: a 403 on one article is usually policy.
    capture_retry: RetrySettings = Field(
        default_factory=lambda: RetrySettings(
            minimum_seconds=15 * 60, maximum_seconds=24 * 60 * 60, factor=3.0, max_failures=5
        )
    )

    # Consecutive host-scoped failures before the host itself is treated as refusing.
    # Below this a run of failures is just bad luck on individual articles.
    host_failure_threshold: int = 5

    # Once tripped, one capture per interval is let through, purely to find out whether
    # the host is still refusing. Without it the breaker freezes its own input.
    host_probe: RetrySettings = Field(
        default_factory=lambda: RetrySettings(
            minimum_seconds=30 * 60, maximum_seconds=24 * 60 * 60, factor=2.0, max_failures=0
        )
    )
