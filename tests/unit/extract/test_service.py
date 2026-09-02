"""The verdict thresholds, which no real page in the corpus reaches one at a time."""

from old_news.config import ExtractSettings
from old_news.extract.service import judge


def test_a_long_enough_body_still_fails_on_too_few_paragraphs():
    """One unbroken blob clears the character floor but is not an article."""
    settings = ExtractSettings()

    assert judge(settings.min_body_chars, settings.min_paragraphs - 1, settings) == (
        False,
        f"only {settings.min_paragraphs - 1} paragraphs",
    )
