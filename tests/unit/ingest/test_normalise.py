import pytest

from old_news.ingest.normalise import canonical_url, content_fingerprint, normalise_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.example.com/a", "https://example.com/a"),
        ("HTTPS://Example.COM/a", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com/", "https://example.com/"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("https://example.com/a?utm_source=rss&utm_medium=feed", "https://example.com/a"),
        ("https://example.com/a?fbclid=xyz&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?CMP=share&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("", ""),
        # Malformed, and handed back rather than raised: one typo'd <link> used to fail the poll.
        ("http://example.com:99999/x", "http://example.com:99999/x"),
        ("https://example.com:8O80/x", "https://example.com:8O80/x"),
        ("http://[bad/x", "http://[bad/x"),
    ],
)
def test_canonical_url(raw: str, expected: str):
    assert canonical_url(raw) == expected


def test_canonical_url_keeps_meaningful_query():
    """Article identity often lives in the query string; only tracking goes."""
    assert canonical_url("https://example.com/index.php?p=1234") == (
        "https://example.com/index.php?p=1234"
    )


def test_canonical_url_leaves_relative_paths_alone():
    assert canonical_url("/news/first") == "/news/first"


def test_normalise_text_collapses_whitespace_and_comments():
    assert normalise_text("<p>a</p>\n\n  <!-- ad slot 4812 -->\t<p>b</p>") == "<p>a</p> <p>b</p>"


def test_fingerprint_ignores_markup_churn():
    """Rotating ad markup must not read as an edit."""
    monday = "<p>Story</p>\n<!-- ad 111 -->"
    tuesday = "<p>Story</p>   <!-- ad 999 -->"

    assert content_fingerprint("Title", monday) == content_fingerprint("Title", tuesday)


def test_fingerprint_catches_a_one_word_redaction():
    before = content_fingerprint("Minister denies wrongdoing", "<p>Body</p>")
    after = content_fingerprint("Minister denies", "<p>Body</p>")

    assert before != after


def test_fingerprint_covers_every_field():
    """Hashing a subset is how a redacted byline goes unrecorded."""
    baseline = content_fingerprint("Title", "Author", "Body")

    assert content_fingerprint("Title", "Someone Else", "Body") != baseline


def test_fingerprint_distinguishes_field_boundaries():
    """'ab' + '' must not hash the same as 'a' + 'b'."""
    assert content_fingerprint("ab", "") != content_fingerprint("a", "b")
