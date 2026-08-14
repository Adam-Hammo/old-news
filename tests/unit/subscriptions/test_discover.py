from old_news.subscriptions.discover import feeds_in

PAGE = b"""<!doctype html>
<html><head>
  <link rel="stylesheet" href="/style.css">
  <link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml">
  <link rel='alternate' type='application/atom+xml' href='https://cdn.example.com/atom'>
  <link rel="alternate" type="text/html" href="/print">
</head><body></body></html>"""


def test_finds_feeds_and_ignores_everything_else():
    assert feeds_in(PAGE, base_url="https://example.com/blog/") == [
        "https://example.com/feed.xml",
        "https://cdn.example.com/atom",
    ]


def test_relative_hrefs_resolve_against_the_page():
    page = b'<link rel="alternate" type="application/rss+xml" href="rss">'

    assert feeds_in(page, base_url="https://example.com/blog/index.html") == [
        "https://example.com/blog/rss"
    ]


def test_multiple_rel_values_still_match():
    page = b'<link rel="alternate home" type="application/rss+xml" href="/f">'

    assert feeds_in(page, base_url="https://example.com/") == ["https://example.com/f"]


def test_duplicates_are_collapsed():
    page = b"""<link rel="alternate" type="application/rss+xml" href="/f">
               <link rel="alternate" type="application/rss+xml" href="/f">"""

    assert feeds_in(page, base_url="https://example.com/") == ["https://example.com/f"]


def test_a_page_without_feeds_yields_nothing():
    assert feeds_in(b"<html><head></head></html>", base_url="https://example.com/") == []
