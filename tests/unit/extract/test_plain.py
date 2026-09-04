"""A reading as one line of prose, which is what a fragment of one has to be."""

from old_news.extract import plain


def test_markdown_furniture_comes_off():
    flat = plain.flatten("## Head\n\n- one\n- two\n\nSee [this](https://example.com/x).")

    assert flat == "Head one two See this ."


# A greedy \S+ eats the closing bracket and the sentence's punctuation with it.
def test_a_url_stops_at_its_bracket():
    assert plain.flatten("Read [it](https://e.com/a) now.") == "Read it now."


def test_an_entity_reads_as_the_character_it_spells():
    assert plain.flatten("Google&#x27;s streets &amp; lanes") == "Google's streets & lanes"


# The `#` strip would otherwise turn `&#x27;` into litter rather than an apostrophe.
def test_an_entity_is_read_before_the_markup_is_stripped():
    assert "#" not in plain.flatten("&#x27;quoted&#x27;")


def test_a_short_line_is_not_cut():
    assert plain.clipped("Short enough", 40) == "Short enough"


def test_a_long_line_is_cut_on_a_word_and_says_so():
    clipped = plain.clipped("word " * 50, 20)

    assert clipped.endswith("…")
    assert len(clipped) <= 21
    assert "wor…" not in clipped
