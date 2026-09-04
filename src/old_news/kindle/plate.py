"""The cover, drawn as SVG because it carries this issue's date and tally."""

from xml.sax.saxutils import escape

# SVG rather than an image: Pillow belongs to `extract/`, and a nameplate is not a
# rendition of anything held. The converter rasterises this, so nothing here draws.

# One exact name. Qt's SVG renderer honours neither a comma-separated stack nor the
# generic `serif` — both fall through to monospace. This one fontconfig aliases to
# Liberation Serif in the image, and it exists outright on a laptop.
SERIF = "Times New Roman"

COVER = (1200, 1600)

NAMEPLATE_LEADING = 210


def _open(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
    )


def _line(x1: int, y: int, x2: int, weight: int) -> str:
    return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#000" stroke-width="{weight}"/>'


def _set(text: str, *, y: int, size: int, width: int, tracking: float = 0) -> str:
    return (
        f'<text x="{width // 2}" y="{y}" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="{size}" font-weight="bold" letter-spacing="{tracking}" '
        f'fill="#000">{escape(text)}</text>'
    )


def cover(name: str, lines: list[str]) -> str:
    """A broadsheet nameplate over the dateline and the tally."""
    width, height = COVER
    inner, edge = 124, 90
    frame = (
        f'<rect x="{edge}" y="{edge}" width="{width - 2 * edge}" '
        f'height="{height - 2 * edge}" fill="none" stroke="#000" stroke-width="3"/>'
    )

    # Stacked a word to a line, which is what makes a nameplate read as one.
    words = name.upper().split()
    top = 640 - (len(words) - 1) * NAMEPLATE_LEADING // 2
    plate = [
        _set(word, y=top + row * NAMEPLATE_LEADING, size=210, width=width)
        for row, word in enumerate(words)
    ]

    parts = [
        _open(width, height),
        frame,
        _line(inner, inner, width - inner, 1),
        *plate,
        _line(inner, 930, width - inner, 4),
        _line(inner, 944, width - inner, 1),
        *(_set(text, y=1010 + row * 58, size=40, width=width) for row, text in enumerate(lines)),
        _line(inner, height - inner - 16, width - inner, 1),
        _line(inner, height - inner, width - inner, 4),
        "</svg>",
    ]
    return "".join(parts)
