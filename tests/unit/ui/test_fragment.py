"""The fragment a search row carries: a window of the reading, with what matched marked."""

from old_news.ui import search

STREET = (
    "The street was widened in 1962 and the shops went with it. Housing density fell by a "
    "third over the decade that followed, and nobody wrote it down at the time."
)


def marked(body: str, terms: str) -> str:
    """The fragment with its markers made visible, so a test can say where they land."""
    return search.fragment(body, terms).replace(search.OPEN, "[").replace(search.CLOSE, "]")


def test_what_matched_is_marked():
    assert "[density]" in marked(STREET, "density")


def test_every_word_that_matched_is_marked():
    fragment = marked(STREET, "housing density")

    assert "[Housing] [density]" in fragment


def test_a_match_early_on_needs_no_run_up():
    assert marked("Density fell. " * 4, "density").startswith("[Density]")


# Otherwise the matched word is the first thing in the window and the sentence it was in
# is the part that got cut.
def test_a_match_further_in_keeps_its_run_up():
    fragment = marked(STREET, "density")

    assert fragment.startswith("…")
    assert "the shops went with it" in fragment


# `…nb didn't overwhelm London` reads as a typo rather than as a cut.
def test_the_run_up_does_not_open_mid_word():
    fragment = marked(STREET, "density")

    assert fragment.startswith("…")
    word, _, _ = fragment.removeprefix("…").partition(" ")
    assert word in STREET.split(), word


def test_a_long_reading_is_cut_to_a_window():
    fragment = search.fragment("Density. " + "word " * 400, "density")

    assert len(fragment) <= search.SNIPPET_CHARS + len(search.OPEN + search.CLOSE) + 1
    assert fragment.endswith("…")


# The index reaches text `flatten` drops, and an unmarked opening paragraph explains
# nothing about why the row is on screen.
def test_a_term_only_in_a_stripped_url_offers_no_fragment():
    assert search.fragment("Read it at https://airbnb.example.com/x for more.", "airbnb") == ""


def test_a_headline_only_match_offers_no_fragment():
    assert search.fragment(STREET, "wombat") == ""


def test_nothing_to_search_for_is_no_fragment():
    assert search.fragment(STREET, "") == ""
    assert search.fragment("", "density") == ""


def test_the_fragment_is_prose_rather_than_the_markdown_it_is_stored_as():
    body = "## Head\n\nThe [density](https://example.com/x) of Google&#x27;s streets fell."

    fragment = marked(body, "density")

    assert "https://" not in fragment
    assert "Google's" in fragment
    assert "[density]" in fragment


# A prefix test, not the index's stemming: it reaches the longer forms of a term and not
# the ones spelt differently, which is why the docstring calls it an approximation.
def test_a_longer_form_of_the_term_is_marked():
    assert "[housings]" in marked("Two housings failed.", "housing")


def test_marking_is_case_insensitive_but_keeps_the_case_it_found():
    assert "[Housing]" in marked("Housing fell.", "housing")
