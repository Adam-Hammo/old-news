"""The teaser, cut from markdown. What must survive, and what must not show."""

from old_news.ui.deck import deck

LIMIT = 220


def test_links_keep_their_anchor_and_lose_their_url():
    assert deck("See [the report](https://example.com/a) for more.", LIMIT) == (
        "See the report for more."
    )


def test_images_go_entirely():
    assert deck("![A chart](https://example.com/c.png)\n\nThe text.", LIMIT) == "The text."


def test_line_markers_open_a_line_and_nothing_else():
    assert deck("## Heading\n\n- one\n- two\n\n> quoted", LIMIT) == "Heading one two quoted"


def test_emphasis_is_unwrapped_but_a_bare_underscore_is_not():
    assert deck("**Bold** and `code` in old_news_web", LIMIT) == "Bold and code in old_news_web"


def test_a_link_the_sql_prefix_cut_in_half_does_not_show():
    assert deck("The whole story. [an anch", LIMIT) == "The whole story."


def test_a_long_body_is_cut_on_a_word():
    text = deck("word " * 200, 20)

    assert text.endswith("…")
    assert len(text) <= 21
    assert "wor…" not in text


def test_a_short_body_is_left_alone():
    assert deck("Short.", LIMIT) == "Short."
