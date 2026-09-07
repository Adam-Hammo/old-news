"""What a reader typed, taken apart. The grammar, and nothing that touches the database."""

import dataclasses
import datetime
import re

# A quoted run is one token however much whitespace is in it, so `from:"Kagi News"` and
# `-"reverse centaurs"` both survive the split.
TOKENS = re.compile(r'-?(?:[a-z]+:)?"[^"]*"|\S+')

# `key:value`, matched only against keys we know: prose has colons in it, and so does
# every URL anybody has pasted into a search box.
OPERATOR = re.compile(r"^(?P<key>[a-z]+):(?P<value>.*)$")

WORD = re.compile(r"\w+")

OPERATORS = frozenset({"from", "by", "after", "before", "is"})

# The two a minus means something for. `-after:` is not a period and `-is:read` is
# `is:unread`, so neither is worth a second spelling.
NEGATABLE = frozenset({"from", "by"})

# What `is:` takes. Read is a tap on a headline; finished is the bottom of the article.
STATES = ("read", "unread", "finished", "unfinished")


class BadQuery(ValueError):
    """Handed an operator it cannot read. Ordinary words are never an error."""


@dataclasses.dataclass(frozen=True, slots=True)
class Term:
    """One thing to match. More than one word means they have to be adjacent."""

    words: tuple[str, ...]
    excluded: bool = False

    @property
    def phrase(self) -> bool:
        return len(self.words) > 1


@dataclasses.dataclass(frozen=True, slots=True)
# The Guardian is 56% of the archive, so excluding a publication is the most useful
# exclusion there is.
class Named:
    """One name asked for, or asked against."""

    value: str
    excluded: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Query:
    """One search, parsed. Every field is what survived, so no caller re-reads the text."""

    terms: tuple[Term, ...] = ()
    # Matched loosely against a publication's title or address: a feed id is not a thing
    # anybody types.
    publications: tuple[Named, ...] = ()
    authors: tuple[Named, ...] = ()
    # `after:` includes its date and `before:` does not, so the pair reads as one period —
    # `after:2026-08 before:2026-09` is August and nothing either side of it.
    since: datetime.date | None = None
    until: datetime.date | None = None
    states: tuple[str, ...] = ()

    @property
    def wanted(self) -> tuple[Term, ...]:
        return tuple(term for term in self.terms if not term.excluded)

    # Without one of these there is no relevance to sort on, so the archive comes back
    # newest first and paged by its own cursor rather than by depth.
    @property
    def ranked(self) -> bool:
        """Whether anything was typed to rank by."""
        return bool(self.wanted)


def _date(key: str, value: str) -> datetime.date:
    """A year, a month or a day, each standing for the first instant of itself."""
    parts = value.split("-")
    if len(parts) <= 3 and all(part.isascii() and part.isdigit() for part in parts):
        year, month, day = (*parts, "1", "1")[:3]
        try:
            return datetime.date(int(year), int(month), int(day))
        except ValueError:
            pass
    raise BadQuery(f"{key}: wants a year, a month or a day, not {value!r}")


def _state(value: str) -> str:
    if value not in STATES:
        raise BadQuery(f"is: wants one of {', '.join(STATES)}, not {value!r}")
    return value


def _split(token: str) -> tuple[bool, str, str, bool]:
    """One token as its four facts: negated, operator, value, and whether it was quoted."""
    negated = token.startswith("-")
    body = token[1:] if negated else token

    found = OPERATOR.match(body)
    key, raw = (found["key"], found["value"]) if found and found["key"] in OPERATORS else ("", body)

    quoted = len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')
    return negated, key, raw[1:-1] if quoted else raw, quoted


def parse(text: str) -> Query:
    """Take a search apart. Only an operator we recognise and cannot read is an error."""
    terms: list[Term] = []
    publications: list[Named] = []
    authors: list[Named] = []
    states: list[str] = []
    since: datetime.date | None = None
    until: datetime.date | None = None

    for token in TOKENS.findall(text):
        negated, key, value, quoted = _split(token)

        if not key:
            words = tuple(WORD.findall(value))
            if not words:
                continue
            # Quotes are the only thing that makes a phrase. `don't` tokenises to two
            # words and stays two words, which is what the box has always done with it.
            if quoted or len(words) == 1:
                terms.append(Term(words=words, excluded=negated))
            else:
                terms.extend(Term(words=(word,), excluded=negated) for word in words)
            continue

        if not value:
            raise BadQuery(f"{key}: wants something after it")
        if negated and key not in NEGATABLE:
            raise BadQuery(f"-{key}: only {' and '.join(sorted(NEGATABLE))} take a minus")
        if key == "from":
            publications.append(Named(value=value, excluded=negated))
        elif key == "by":
            authors.append(Named(value=value, excluded=negated))
        elif key == "is":
            states.append(_state(value))
        elif key == "after":
            since = _date(key, value)
        else:
            until = _date(key, value)

    return Query(
        terms=tuple(terms),
        publications=tuple(publications),
        authors=tuple(authors),
        since=since,
        until=until,
        states=tuple(states),
    )
