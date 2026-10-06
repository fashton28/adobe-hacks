from typing import List

import skia  # type: ignore

from cr_renderer.fonts import FontManager


def char_widths(
    font_manager: FontManager, family: str, weight: str, style: str, size: float, text: str
) -> List[float]:
    """Per-character advance widths for `text`, using the same font lookup
    and skia measurement cr-renderer itself uses to draw glyphs - so wrap
    decisions match what will actually be rendered."""
    if not text:
        return []
    ttf_bytes = font_manager.lookup(family, weight, style)
    typeface = skia.Typeface.MakeFromData(ttf_bytes)
    font = skia.Font(typeface, size)
    glyphs = font.textToGlyphs(text)
    return list(font.getWidths(glyphs))


def wrap_text(text: str, widths: List[float], max_width: float) -> str:
    """Greedy word-wrap that only turns existing spaces into newlines.

    This keeps the wrapped string exactly the same length as the input,
    with every character at the same index it started at (a space simply
    becomes a "\\n" in place). That means style-run start/end offsets
    computed against the original text stay valid after wrapping, with no
    remapping needed. A single word wider than `max_width` is left to
    overflow its line rather than being hard-broken mid-word.
    """
    if not text or max_width <= 0:
        return text

    chars = list(text)
    line_width = 0.0
    last_space_idx = None

    for i, c in enumerate(chars):
        if c == "\n":
            line_width = 0.0
            last_space_idx = None
            continue

        w = widths[i] if i < len(widths) else 0.0
        if line_width + w > max_width and last_space_idx is not None:
            chars[last_space_idx] = "\n"
            line_width = sum(
                widths[j] for j in range(last_space_idx + 1, i + 1) if chars[j] != "\n"
            )
            last_space_idx = None
        else:
            line_width += w

        if c == " ":
            last_space_idx = i

    return "".join(chars)
