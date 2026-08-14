import pytest

from old_news.subscriptions.opml import MAX_BYTES, OpmlError, Outline, parse, render

NESTED = b"""<?xml version="1.0"?>
<opml version="2.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline text="News" title="News">
      <outline text="The Example" title="The Example" type="rss"
               xmlUrl="https://example.com/feed.xml" htmlUrl="https://example.com/"/>
      <outline text="Another" title="Another" type="rss" xmlUrl="https://another.com/rss"/>
    </outline>
    <outline text="Loose" title="Loose" type="rss" xmlUrl="https://loose.com/feed"/>
  </body>
</opml>
"""


def test_folders_flatten_to_a_category():
    outlines = parse(NESTED)

    assert [(o.title, o.category) for o in outlines] == [
        ("The Example", "News"),
        ("Another", "News"),
        ("Loose", ""),
    ]


def test_feed_and_site_urls_are_kept_apart():
    first = parse(NESTED)[0]

    assert first.url == "https://example.com/feed.xml"
    assert first.site_url == "https://example.com/"
    assert first.needs_discovery is False


def test_an_outline_naming_only_a_site_is_marked_for_discovery():
    """Exporters emit these, and dropping them loses a subscription."""
    data = b"""<opml version="2.0"><body>
      <outline text="Blog" htmlUrl="https://blog.example.com/"/>
    </body></opml>"""

    outline = parse(data)[0]

    assert outline.url == "https://blog.example.com/"
    assert outline.needs_discovery is True


def test_deeper_nesting_uses_the_nearest_named_folder():
    data = b"""<opml version="2.0"><body>
      <outline text="Outer">
        <outline text="Inner">
          <outline text="Deep" xmlUrl="https://deep.example.com/feed"/>
        </outline>
      </outline>
    </body></opml>"""

    assert parse(data)[0].category == "Inner"


def test_missing_body_is_an_error():
    with pytest.raises(OpmlError):
        parse(b'<opml version="2.0"></opml>')


def test_malformed_xml_is_an_error():
    with pytest.raises(OpmlError):
        parse(b"<opml><body>")


def test_oversized_input_is_refused():
    with pytest.raises(OpmlError):
        parse(b"<opml/>" + b" " * MAX_BYTES)


def test_round_trip_preserves_urls_titles_and_categories():
    """Order is not preserved — render sorts, so exports don't churn in git."""
    original = parse(NESTED)

    restored = parse(render(original))

    def fields(outlines):
        return sorted((o.url, o.title, o.category, o.site_url) for o in outlines)

    assert fields(restored) == fields(original)


def test_export_is_byte_stable_regardless_of_input_order():
    outlines = parse(NESTED)

    assert render(list(reversed(outlines))) == render(outlines)


def test_render_escapes_attributes():
    rendered = render([Outline(url="https://x.com/?a=1&b=2", title='Ampersands & "quotes"')])

    assert b"&amp;" in rendered
    assert parse(rendered)[0].title == 'Ampersands & "quotes"'


def test_entity_expansion_is_refused():
    """A 1 KB file with nested entities is the attack; the size cap is no defence."""
    bomb = b"""<?xml version="1.0"?><!DOCTYPE opml [
      <!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
      <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>
    <opml version="2.0"><body><outline text="&c;" xmlUrl="https://x/f"/></body></opml>"""

    with pytest.raises(OpmlError):
        parse(bomb)
