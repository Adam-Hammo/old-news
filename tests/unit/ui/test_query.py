"""The grammar. Every one of these is something a reader would plausibly type."""

import datetime

import pytest

from old_news.ui.query import BadQuery, Named, Query, Term, parse


def words(query: Query) -> list[tuple[str, ...]]:
    return [term.words for term in query.terms if not term.excluded]


def without(query: Query) -> list[tuple[str, ...]]:
    return [term.words for term in query.terms if term.excluded]


def test_bare_words_are_still_bare_words():
    assert words(parse("superannuation reform")) == [("superannuation",), ("reform",)]


def test_nothing_typed_is_not_an_error():
    assert parse("   ") == Query()


# The one that silently did the opposite: a minus used to be dropped and the word required.
def test_a_minus_excludes():
    query = parse("superannuation -liberal")

    assert words(query) == [("superannuation",)]
    assert without(query) == [("liberal",)]


# The other one: the quotes used to be dropped and the words merely all required.
def test_quotes_make_a_phrase():
    assert parse('"reverse centaurs"').terms == (Term(words=("reverse", "centaurs")),)


def test_a_phrase_can_be_excluded():
    query = parse('enshittification -"reverse centaurs"')

    assert words(query) == [("enshittification",)]
    assert without(query) == [("reverse", "centaurs")]


# An apostrophe tokenises to two words. It has always meant both, and it still does —
# quotes are the only thing that asks for adjacency.
def test_an_apostrophe_is_two_words_and_not_a_phrase():
    query = parse("don't")

    assert words(query) == [("don",), ("t",)]
    assert not any(term.phrase for term in query.terms)


def test_a_one_word_quote_is_just_that_word():
    assert parse('"guardian"').terms == (Term(words=("guardian",)),)


def test_a_publication_is_named_not_identified():
    assert parse("from:pluralistic").publications == (Named(value="pluralistic"),)


# The Guardian is 56% of the archive, so excluding a publication is the most useful
# exclusion there is — and it used to parse as asking for it.
def test_a_publication_can_be_excluded():
    assert parse("-from:guardian").publications == (Named(value="guardian", excluded=True),)


def test_an_author_can_be_too():
    assert parse("-by:doctorow").authors == (Named(value="doctorow", excluded=True),)


# `-after:` is not a period and `-is:read` is `is:unread`, so neither is worth a second
# spelling — and silently meaning the opposite is what this grammar exists to stop.
@pytest.mark.parametrize("typed", ["-is:read", "-after:2026-08", "-before:2026-09"])
def test_a_minus_on_anything_else_says_so_rather_than_inverting(typed: str):
    with pytest.raises(BadQuery, match="minus"):
        parse(typed)


def test_a_name_with_a_space_in_it_survives_the_split():
    assert parse('from:"Kagi News" enshittification') == Query(
        terms=(Term(words=("enshittification",)),), publications=(Named(value="Kagi News"),)
    )


def test_an_author_is_a_field_no_menu_could_hold():
    assert parse("by:doctorow").authors == (Named(value="doctorow"),)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("after:2026", datetime.date(2026, 1, 1)),
        ("after:2026-08", datetime.date(2026, 8, 1)),
        ("after:2026-08-15", datetime.date(2026, 8, 15)),
    ],
)
def test_a_date_can_be_a_year_a_month_or_a_day(typed: str, expected: datetime.date):
    assert parse(typed).since == expected


# The pair has to read as one whole period, or nobody can say "August" without arithmetic.
def test_after_and_before_bracket_exactly_one_month():
    query = parse("after:2026-08 before:2026-09")

    assert (query.since, query.until) == (datetime.date(2026, 8, 1), datetime.date(2026, 9, 1))


@pytest.mark.parametrize(
    "typed",
    [
        pytest.param("after:banana", id="not-a-date-at-all"),
        pytest.param("after:2026-13", id="no-thirteenth-month"),
        # The month after this one does not fit in a date, which used to be a 500.
        pytest.param("before:10000-01", id="past-the-last-month-there-is"),
        pytest.param("after:2026-", id="half-typed"),
    ],
)
def test_a_date_that_is_not_one_says_so(typed: str):
    with pytest.raises(BadQuery):
        parse(typed)


def test_a_state_that_is_not_one_says_so():
    with pytest.raises(BadQuery, match="is:"):
        parse("is:interesting")


def test_an_operator_with_nothing_after_it_says_so():
    with pytest.raises(BadQuery, match="from:"):
        parse("from:")


def test_the_states_are_the_flags_already_on_the_row():
    assert parse("is:unread is:finished").states == ("unread", "finished")


# Prose has colons in it and so does every URL. Only a key we know is an operator, and
# an unquoted token's words are each required and none of them adjacent — as before.
def test_an_unknown_key_stays_text():
    assert words(parse("https://example.com/a")) == [
        ("https",),
        ("example",),
        ("com",),
        ("a",),
    ]


def test_a_negated_unknown_key_is_still_excluded_text():
    assert without(parse("-notes:2026")) == [("notes",), ("2026",)]


# Without one, there is no relevance to sort on and the archive falls back to date order.
def test_a_query_with_no_words_to_rank_by_says_so():
    assert not parse("from:pluralistic is:unread").ranked
    assert not parse("-liberal").ranked
    assert parse("enshittification from:pluralistic").ranked


def test_everything_at_once():
    query = parse('"reverse centaurs" -google from:pluralistic by:doctorow after:2026-08 is:unread')

    assert query == Query(
        terms=(
            Term(words=("reverse", "centaurs")),
            Term(words=("google",), excluded=True),
        ),
        publications=(Named(value="pluralistic"),),
        authors=(Named(value="doctorow"),),
        since=datetime.date(2026, 8, 1),
        states=("unread",),
    )
