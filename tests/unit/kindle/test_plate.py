"""The cover, which is the one part of the book that changes every week."""

from xml.etree import ElementTree

from old_news.kindle import plate


def _drawn(name: str = "Old News", lines: list[str] | None = None) -> str:
    return plate.cover(name, lines if lines is not None else ["4 September 2026", "14 articles"])


def test_a_cover_is_well_formed_svg():
    """The converter rasterises it, and a broken one is a book with no cover."""
    root = ElementTree.fromstring(_drawn())

    assert root.tag.endswith("svg")
    assert root.attrib["width"] == str(plate.COVER[0])


def test_the_nameplate_is_stacked_a_word_to_a_line():
    text = [node.text for node in ElementTree.fromstring(_drawn()).iter() if node.text]

    assert "OLD" in text
    assert "NEWS" in text


def test_a_one_word_name_takes_one_line():
    text = [node.text for node in ElementTree.fromstring(_drawn("Dispatch")).iter() if node.text]

    assert "DISPATCH" in text


def test_the_issue_lines_are_set_under_the_rules():
    text = [node.text for node in ElementTree.fromstring(_drawn()).iter() if node.text]

    assert "4 September 2026" in text
    assert "14 articles" in text


def test_a_name_with_markup_in_it_cannot_break_the_drawing():
    root = ElementTree.fromstring(_drawn("<script/>Paper"))
    text = [node.text for node in root.iter() if node.text]

    assert "<SCRIPT/>PAPER" in text


def test_the_only_font_named_is_one_qt_resolves():
    """Neither a comma-separated stack nor the generic `serif` survives Qt's SVG reader."""
    assert "," not in plate.SERIF
    assert plate.SERIF != "serif"
