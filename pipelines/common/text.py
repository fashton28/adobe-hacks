"""Text measurement / fitting using the brand fonts (Pillow only, no renderer dependency).

Mirrors the renderer's wrapping rule (greedy, breaks only at spaces, a word
wider than the box overflows) so fit decisions match what gets drawn. Widths
are measured at a fixed 100px reference size and scaled linearly.
"""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONTS_DIR = Path(__file__).resolve().parents[2] / "brand_kit" / "fonts"
_REF = 100.0
_SAFETY = 1.02  # headroom for kerning / bold style-runs


@lru_cache(maxsize=None)
def _font_path(family: str, bold: bool, italic: bool) -> str | None:
    base = family.replace(" ", "")
    suffix = ("Bold" if bold else "") + ("Italic" if italic else "") or "Regular"
    for suf in (suffix, "Bold" if bold else "Regular", "Regular"):
        p = FONTS_DIR / f"{base}-{suf}.ttf"
        if p.exists():
            return str(p)
    any_font = sorted(FONTS_DIR.glob("*.ttf"))
    return str(any_font[0]) if any_font else None


@lru_cache(maxsize=None)
def _ref_font(path: str):
    return ImageFont.truetype(path, _REF)


@lru_cache(maxsize=200_000)
def _ref_width(path: str | None, text: str) -> float:
    if path is None:
        return 0.55 * _REF * len(text)
    return _ref_font(path).getlength(text)


def _style(el: dict) -> tuple[str | None, float]:
    path = _font_path(
        el.get("font_family", ""),
        el.get("font_weight", "regular") == "bold",
        el.get("font_style", "normal") == "italic",
    )
    return path, float(el.get("letter_spacing", 0.0) or 0.0)


def measure(el: dict, size: float, width: float) -> tuple[int, float]:
    """(line_count, widest_line_px) of el's content wrapped at `width` and `size`."""
    path, ls = _style(el)
    k = size / _REF * _SAFETY

    def w(s: str) -> float:
        return _ref_width(path, s) * k + ls * len(s)

    space = w(" ")
    lines, widest = 0, 0.0
    for para in str(el.get("content", "")).split("\n"):
        cur = 0.0
        started = False
        lines += 1
        for word in para.split(" "):
            ww = w(word)
            if started and cur + space + ww > width:
                widest = max(widest, cur)
                lines += 1
                cur = ww
            else:
                cur = cur + space + ww if started else ww
            started = True
        widest = max(widest, cur)
    return lines, widest


def text_height(el: dict, size: float, lines: int) -> float:
    return lines * size * float(el.get("line_height", 1.2))


def fit_text(el: dict, width: float, max_h: float, max_size: float) -> tuple[float, float]:
    """Largest font size <= max_size whose wrapped text fits width x max_h.

    Returns (size, needed_height). Falls back to 1px if nothing fits.
    """

    def fits(size: float) -> tuple[bool, float]:
        lines, widest = measure(el, size, width)
        h = text_height(el, size, lines)
        return widest <= width and h <= max_h, h

    max_size = max(1.0, max_size)
    ok, h = fits(max_size)
    if ok:
        return max_size, h
    lo, hi = 1.0, max_size
    if not fits(lo)[0]:
        return 1.0, fits(lo)[1]
    for _ in range(14):
        mid = (lo + hi) / 2
        if fits(mid)[0]:
            lo = mid
        else:
            hi = mid
    return lo, fits(lo)[1]
