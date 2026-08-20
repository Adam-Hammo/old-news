"""The extractor against real pages, because a synthetic one proves nothing about a site."""

from old_news.config import ExtractSettings
from old_news.db import ImageRole
from old_news.extract import article
from old_news.extract.service import judge

GUARDIAN_URL = "https://www.theguardian.com/society/2026/aug/19/benefits-disabled-young-people"


def test_a_real_article_comes_out_whole(page):
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    assert got.char_count > 3000
    assert got.paragraph_count > 10
    assert "charities" in got.body


def test_a_real_article_carries_what_the_page_claims(page):
    """Free while we are in there, and impossible to get later once the page has gone."""
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    assert got.title
    assert got.byline
    assert got.site_name == "The Guardian"
    assert got.page_type == "article"
    assert got.published_claim.startswith("2026-")


def test_a_real_article_yields_its_outbound_links(page):
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    assert len(got.links) > 1
    assert all(link.url.startswith("http") for link in got.links)
    assert all(link.anchor for link in got.links)


def test_a_real_article_yields_a_lead_image(page):
    """What a card and a Kindle cover want, and the only image fetched unasked."""
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    leads = [image for image in got.images if image.role == ImageRole.LEAD]
    assert len(leads) == 1
    assert leads[0].url.startswith("http")


def test_a_consent_wall_fails_the_quality_signal(page):
    """The failure that matters. It extracts cleanly and is not an article."""
    got = article.parse(page("consent-wall.html"), "https://example.com/article")

    ok, note = judge(got, ExtractSettings())
    assert not ok
    assert note


def test_a_real_article_passes_the_quality_signal(page):
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    ok, note = judge(got, ExtractSettings())
    assert ok
    assert note == ""


def test_nothing_extractable_is_not_an_error():
    got = article.parse("<html><body></body></html>", "https://example.com/a")

    assert got.body == ""
    assert not judge(got, ExtractSettings())[0]
