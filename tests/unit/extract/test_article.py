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

    ok, note = judge(got.char_count, got.paragraph_count, ExtractSettings())
    assert not ok
    assert note


def test_a_real_article_passes_the_quality_signal(page):
    got = article.parse(page("guardian-article.html"), GUARDIAN_URL)

    ok, note = judge(got.char_count, got.paragraph_count, ExtractSettings())
    assert ok
    assert note == ""


def test_nothing_extractable_is_not_an_error():
    got = article.parse("<html><body></body></html>", "https://example.com/a")

    assert got.body == ""
    assert not judge(got.char_count, got.paragraph_count, ExtractSettings())[0]


CONVERSATION_URL = (
    "https://theconversation.com/who-should-assume-the-risk-when-art-gets-controversial-"
    "the-artist-or-their-employer-289492"
)
XKCD_URL = "https://xkcd.com/3292/"
QUOTED = "it is much more about managing the different perspectives"


def test_a_quoted_block_is_marked_as_one(page):
    """Trafilatura's markdown drops the mark, so a quotation arrived as the author's
    own next paragraph and nothing in the reading said otherwise."""
    got = article.parse(page("conversation-article.html"), CONVERSATION_URL)

    quoted = [line for line in got.body.splitlines() if line.startswith("> ")]
    assert any(QUOTED in line for line in quoted)


def test_a_quotation_reaches_the_reader_only_as_a_quotation(page):
    got = article.parse(page("conversation-article.html"), CONVERSATION_URL)

    carrying = [line for line in got.body.splitlines() if QUOTED in line]
    assert carrying and all(line.startswith("> ") for line in carrying)


def test_headings_and_quotes_are_what_a_reading_is_measured_to_have_kept(page):
    got = article.parse(page("conversation-article.html"), CONVERSATION_URL)

    marked = [line for line in got.body.splitlines() if line.startswith(("#", ">"))]

    assert got.structure_count == len(marked) > 1


def test_a_feed_item_that_is_only_a_picture_keeps_the_picture(page):
    """A comic or a photo has no prose to find, and trafilatura returns nothing for it.
    Dropped, the item reads as a fetch that failed rather than as what was published."""
    got = article.parse_fragment(page("xkcd-feed-item.html"), XKCD_URL)

    assert got.images and got.images[0].url.endswith("geology_class.png")
    assert got.structure_count == 1


def test_a_salvaged_picture_carries_the_words_hung_off_it(page):
    got = article.parse_fragment(page("xkcd-feed-item.html"), XKCD_URL)

    assert "AI review bombing" in got.body
    assert got.body.endswith('")')


def test_a_feed_item_with_prose_is_still_read_rather_than_salvaged():
    """The salvage is a fallback. Anything trafilatura will call an article stays its own."""
    got = article.parse_fragment(
        "<div><p>The council voted on Tuesday to defer the rezoning for another year, "
        "after a submission period that drew nine hundred responses.</p>"
        "<blockquote><p>We heard you.</p></blockquote></div>",
        "https://example.com/a",
    )

    assert got.body.startswith("The council voted")
    assert "> We heard you." in got.body
