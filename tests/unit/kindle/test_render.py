"""Turning one reading into one page, and what gets left off it."""

from old_news.kindle import render


def test_markdown_becomes_html():
    assert render.to_html("A **claim**.", {}) == "<p>A <strong>claim</strong>.</p>\n"


def test_publisher_html_is_escaped_rather_than_passed():
    """Nothing a publisher wrote reaches the book as markup, so the output is always ours."""
    assert "<script>" not in render.to_html("<script>alert(1)</script>", {})


def test_an_image_points_at_the_copy_in_the_book():
    html = render.to_html("![a chart](https://cdn.example.com/a.jpg)", {})
    assert "<img" not in html

    mapped = render.to_html(
        "![a chart](https://cdn.example.com/a.jpg)",
        {"https://cdn.example.com/a.jpg": "../images/abc.jpg"},
    )
    assert '<img src="../images/abc.jpg" alt="a chart"/>' in mapped


def test_a_dropped_image_takes_its_paragraph_with_it():
    """A grey box is worse than nothing, and so is the empty line it sat on."""
    assert render.to_html("![gone](https://cdn.example.com/x.jpg)\n\nText.\n", {}) == (
        "<p>Text.</p>\n"
    )


def test_the_headline_the_extractor_kept_is_not_printed_twice():
    body = "# A quiet street in Leeds\n\nThe residents say.\n"
    assert render.without_title(body, "A quiet street in Leeds") == "The residents say.\n"


def test_a_first_heading_that_is_not_the_headline_stays():
    body = "# Part one\n\nThe residents say.\n"
    assert render.without_title(body, "A quiet street in Leeds") == body


def test_a_headline_matches_past_its_punctuation():
    body = "## Reaping the Whirlwind — inside the crash\n\nOn the ninth.\n"
    title = "Reaping the Whirlwind | Inside the Crash"

    assert render.without_title(body, title) == "On the ninth.\n"


def test_an_outlet_that_is_also_the_author_is_credited_once():
    assert render.byline("Admiral Cloudberg", "Admiral Cloudberg", "26 August 2026") == (
        "Admiral Cloudberg · 26 August 2026"
    )


def test_a_byline_leaves_out_what_nobody_recorded():
    assert render.byline("ProPublica", "", "") == "ProPublica"


def test_reading_time_is_never_nothing():
    assert render.minutes(10) == 1
    assert render.minutes(26_200) == 20


def test_a_teaser_is_prose_with_the_markup_taken_out():
    teaser = render.teaser("## Head\n\n- one\n- two\n\nSee [this](https://example.com/x).")
    assert teaser == "Head one two See this ."


def test_a_long_teaser_stops_on_a_word():
    teaser = render.teaser("word " * 200)
    assert len(teaser) <= render.TEASER_CHARS + 1
    assert teaser.endswith("…")


def test_a_page_carries_the_headline_the_byline_and_the_source():
    page = render.page(
        title="A quiet street",
        outlet="The Guardian",
        author="Priya Raman",
        dateline="30 August 2026",
        url="https://example.com/a",
        lead="../images/abc.jpg",
        body="<p>Text.</p>",
    )

    assert "<h1>A quiet street</h1>" in page
    assert "The Guardian · Priya Raman · 30 August 2026" in page
    assert '<img src="../images/abc.jpg"' in page
    assert 'href="https://example.com/a"' in page


def test_a_page_with_no_lead_has_no_hole_where_one_would_be():
    page = render.page(
        title="A quiet street",
        outlet="The Guardian",
        author="",
        dateline="",
        url="https://example.com/a",
        lead="",
        body="<p>Text.</p>",
    )

    assert "<img" not in page


def test_a_title_with_markup_in_it_is_escaped():
    page = render.page(
        title="A <script> in the works",
        outlet="",
        author="",
        dateline="",
        url="https://example.com/a",
        lead="",
        body="",
    )

    assert "<script>" not in page
