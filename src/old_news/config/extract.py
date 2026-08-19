from pydantic import BaseModel


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
