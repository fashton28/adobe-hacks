"""Renderer-aware text measurement using local brand fonts, without PNG rendering.

Skia advances match the vendored converter, including word wrapping, integer
paint sizes and style runs. Pillow provides a conservative fallback when the
renderer dependencies are absent. Neither path fetches fonts from the network.
"""

from functools import cache, lru_cache
from pathlib import Path

from PIL import ImageFont

try:
    import skia
except ImportError:
    skia = None

FONTS_DIR = Path(__file__).resolve().parents[2] / "brand_kit" / "fonts"
_REF = 100.0
_SAFETY = 1.02  # headroom for kerning / bold style-runs


@cache
def _font_path(family: str, bold: bool, italic: bool) -> str | None:
    base = family.replace(" ", "")
    suffix = ("Bold" if bold else "") + ("Italic" if italic else "") or "Regular"
    for suf in (suffix, "Bold" if bold else "Regular", "Regular"):
        p = FONTS_DIR / f"{base}-{suf}.ttf"
        if p.exists():
            return str(p)
    any_font = sorted(FONTS_DIR.glob("*.ttf"))
    return str(any_font[0]) if any_font else None


@cache
def _ref_font(path: str):
    return ImageFont.truetype(path, int(_REF))


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


@lru_cache(maxsize=32)
def _typeface(path: str):
    # The bytes overload can borrow the Python buffer on Windows. Cached
    # typefaces must own their data after this function returns.
    return skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(Path(path).read_bytes()))


@lru_cache(maxsize=50_000)
def _advances(path: str | None, text: str, size: float) -> tuple[float, ...]:
    if skia is not None and path is not None:
        font = skia.Font(_typeface(path), size)
        return tuple(font.getWidths(font.textToGlyphs(text)))
    return tuple(_ref_width(path, char) * size / _REF * _SAFETY for char in text)


def measure(el: dict, size: float, width: float) -> tuple[int, float]:
    """Measure by typography values, never by element id or object identity.

    Row search asks for the same text/size/width many times. The bounded cache
    includes every property that affects wrapping or painted advances, so
    edited copy, spacing and style runs cannot reuse stale measurements.
    """
    runs = tuple(tuple((key, run[key]) for key in ("start", "end", "font_weight", "font_style") if key in run)
                 for run in el.get("style_runs") or [])
    return _measure_cached(el.get("font_family", ""), el.get("font_weight", "regular"),
                           el.get("font_style", "normal"), str(el.get("content", "")),
                           el.get("font_size", size), float(el.get("letter_spacing", 0) or 0),
                           runs, size, width, skia is not None)


@lru_cache(maxsize=16_384)
def _measure_cached(family, weight, style, content, original_size, spacing, runs, size, width, use_skia):
    el = {"font_family": family, "font_weight": weight, "font_style": style,
          "content": content, "font_size": original_size, "letter_spacing": spacing,
          "style_runs": [dict(run) for run in runs]}
    return _measure_uncached(el, size, width)


def _measure_uncached(el: dict, size: float, width: float) -> tuple[int, float]:
    """Measure the converter's wrapping and painted advances without rendering.

    Skia is used when installed (the production renderer requires it). Pillow
    is a conservative development fallback. Wrapping uses the base font;
    painting uses integer font sizes, spacing and inclusive style-run ends,
    matching the vendored converter even where it differs from the schema.
    Spacing scales with size, just as placement scales it in output JSON.
    """
    path, spacing = _style(el)
    spacing *= size / max(el.get("font_size", size), 1)
    content = str(el.get("content", ""))
    advances = _advances(path, content, float(size))
    chars = list(content)
    line_width, last_space = 0.0, None
    for i, char in enumerate(chars):
        if char == "\n":
            line_width, last_space = 0.0, None
            continue
        if line_width + advances[i] > width and last_space is not None:
            chars[last_space] = "\n"
            line_width = sum(advances[last_space + 1:i + 1])
            last_space = None
        else:
            line_width += advances[i]
        if char == " ":
            last_space = i

    styles = [(el.get("font_weight") == "bold", el.get("font_style") == "italic")] * len(chars)
    for run in el.get("style_runs") or []:
        for i in range(max(0, run.get("start", 0)), min(len(chars), run.get("end", len(chars) - 1) + 1)):
            bold, italic = styles[i]
            styles[i] = (run.get("font_weight", "bold" if bold else "regular") == "bold",
                         run.get("font_style", "italic" if italic else "normal") == "italic")
    painted = {}
    for bold, italic in set(styles):
        fp = _font_path(el.get("font_family", ""), bold, italic)
        painted[bold, italic] = _advances(fp, content, float(max(1, int(size))))
    lines, widest, cur, count = 1, 0.0, 0.0, 0
    for i, char in enumerate(chars):
        if char == "\n":
            widest, cur, count = max(widest, cur), 0.0, 0
            lines += 1
        else:
            cur += painted[styles[i]][i] + (spacing if count else 0)
            count += 1
    return lines, max(widest, cur)


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
