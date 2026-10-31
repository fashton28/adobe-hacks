"""Renderer-aware text measurement using local brand fonts, without PNG rendering.

The official converter wraps text with Skia advances at the JSON font size,
then cr-renderer paints every glyph at `int(font_size)`. Layout therefore
emits integer font sizes (`paint_size`) so wrapping and painting agree, and
measures exactly what will be painted: style runs, letter spacing per span
and inclusive run ends. Skia uses the host platform's glyph metrics (hinted
integer advances on Linux, fractional advances on macOS), which is also what
the renderer on that host uses. Pillow is a conservative fallback when the
renderer dependencies are absent. Nothing is fetched from the network.
"""

import math
from functools import cache, lru_cache
from itertools import accumulate
from pathlib import Path

from PIL import ImageFont

try:
    import skia
except ImportError:
    skia = None

FONTS_DIR = Path(__file__).resolve().parents[2] / "brand_kit" / "fonts"
_REF = 100.0
_SAFETY = 1.02  # Pillow fallback headroom for kerning / bold style-runs
WRAP_SLACK = 0.5  # px added to tightened boxes; keeps converter wrapping identical


def paint_size(size: float) -> int:
    """The integer size cr-renderer paints for a requested size (never below 1)."""
    return max(1, math.floor(size + 1e-9))


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


@lru_cache(maxsize=32)
def _typeface(path: str):
    # The bytes overload can borrow the Python buffer on Windows. Cached
    # typefaces must own their data after this function returns.
    return skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(Path(path).read_bytes()))


@lru_cache(maxsize=4096)
def _advances(path: str | None, text: str, size: float) -> tuple[float, ...]:
    if skia is not None and path is not None:
        font = skia.Font(_typeface(path), size)
        return tuple(font.getWidths(font.textToGlyphs(text)))
    return tuple(_ref_width(path, char) * size / _REF * _SAFETY for char in text)


def text_key(el: dict) -> tuple:
    """Every typography value that affects wrapping or painting, size excluded."""
    style_runs = el.get("style_runs")
    runs = tuple(tuple((key, run[key]) for key in ("start", "end", "font_weight", "font_style", "color") if key in run)
                 for run in style_runs) if style_runs else ()
    return (el.get("font_family", ""), el.get("font_weight", "regular"), el.get("font_style", "normal"),
            str(el.get("content", "")), el.get("font_size"), float(el.get("letter_spacing", 0) or 0), runs)


def _key(el: dict, size: float, base: tuple | None = None) -> tuple:
    base = base or text_key(el)
    if base[4] is None:  # no source size: spacing is already at this size
        base = (*base[:4], size, *base[5:])
    return (*base, float(size), skia is not None)


@lru_cache(maxsize=8192)
def _prepared(family, weight, style, content, original_size, spacing, runs, size, use_skia):
    """Per-size tables: wrap tokens plus painted prefix sums and span breaks."""
    bold0, italic0 = weight == "bold", style == "italic"
    wrap = _advances(_font_path(family, bold0, italic0), content, size)
    tokens, i, n = [], 0, len(content)
    while i < n:
        c = content[i]
        if c in " \n":
            tokens.append((c, i, i + 1, wrap[i]))
            i += 1
            continue
        j = i
        while j < n and content[j] not in " \n":
            j += 1
        tokens.append(("w", i, j, sum(wrap[i:j])))
        i = j
    styles = [(bold0, italic0, None)] * n
    for run in map(dict, runs):
        for k in range(max(0, run.get("start", 0)), min(n, run.get("end", n - 1) + 1)):
            bold, italic, color = styles[k]
            styles[k] = (run.get("font_weight", "bold" if bold else "regular") == "bold",
                         run.get("font_style", "italic" if italic else "normal") == "italic",
                         run.get("color", color))
    painted_size = float(paint_size(size))
    tables = {}
    for bold, italic in {(b, it) for b, it, _ in styles}:
        tables[bold, italic] = _advances(_font_path(family, bold, italic), content, painted_size)
    painted = [tables[b, it][k] for k, (b, it, _) in enumerate(styles)]
    # cr-renderer adds letter spacing between glyphs inside one style span;
    # each span boundary within a line drops one spacing step.
    changes = [0] + [int(styles[k] != styles[k - 1]) for k in range(1, n)]
    scaled_spacing = spacing * size / max(original_size, 1)
    return tuple(tokens), (0.0, *accumulate(painted)), (0, *accumulate(changes)), scaled_spacing


def _wrap(tokens, width):
    """Mirror renderer/converter/wrap.py: (line spans, wrap widths incl. break space)."""
    lines, extents = [], []
    start, line_w, last_space, since_space = 0, 0.0, None, 0.0
    for kind, a, b, w in tokens:
        if kind == "\n":
            lines.append((start, a))
            extents.append(line_w)
            start, line_w, last_space, since_space = b, 0.0, None, 0.0
            continue
        if line_w + w > width and last_space is not None:
            lines.append((start, last_space))
            extents.append(line_w - since_space)
            start, line_w = last_space + 1, since_space + w
            last_space = None
        else:
            line_w += w
        if kind == " ":
            last_space, since_space = a, 0.0
        else:
            since_space += w
    lines.append((start, tokens[-1][2] if tokens else 0))
    extents.append(line_w)
    return lines, extents


def _painted(line, prefix, changes, spacing):
    a, b = line
    if b <= a:
        return 0.0
    spans = 1 + changes[b] - changes[a + 1]  # style changes at a+1 .. b-1
    return prefix[b] - prefix[a] + spacing * (b - a - spans)


@lru_cache(maxsize=65_536)
def _measure_key(key, width):
    tokens, prefix, changes, spacing = _prepared(*key)
    lines, _ = _wrap(tokens, width)
    return len(lines), max(_painted(line, prefix, changes, spacing) for line in lines)


def measure(el: dict, size: float, width: float, base: tuple | None = None) -> tuple[int, float]:
    """(line count, widest painted line) for `el` at `size` wrapped to `width`.

    Measurement depends on typography values only, never on element ids or
    object identity, so edited copy, spacing and style runs cannot reuse
    stale results. `base` may carry a precomputed `text_key(el)`.
    """
    return _measure_key(_key(el, size, base), float(width))


def _measure_uncached(el: dict, size: float, width: float) -> tuple[int, float]:
    """Reference character-by-character implementation (tests compare against it)."""
    family = el.get("font_family", "")
    bold0, italic0 = el.get("font_weight") == "bold", el.get("font_style") == "italic"
    spacing = float(el.get("letter_spacing", 0.0) or 0.0) * size / max(el.get("font_size", size), 1)
    content = str(el.get("content", ""))
    advances = _advances(_font_path(family, bold0, italic0), content, float(size))
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
    styles = [(bold0, italic0, None)] * len(chars)
    for run in el.get("style_runs") or []:
        for i in range(max(0, run.get("start", 0)), min(len(chars), run.get("end", len(chars) - 1) + 1)):
            bold, italic, color = styles[i]
            styles[i] = (run.get("font_weight", "bold" if bold else "regular") == "bold",
                         run.get("font_style", "italic" if italic else "normal") == "italic",
                         run.get("color", color))
    painted = {(b, it): _advances(_font_path(family, b, it), content, float(paint_size(size)))
               for b, it, _ in set(styles)}
    lines, widest, cur, count = 1, 0.0, 0.0, 0
    for i, char in enumerate(chars):
        if char == "\n":
            widest, cur, count = max(widest, cur), 0.0, 0
            lines += 1
            continue
        same_span = count and styles[i] == styles[i - 1]
        cur += painted[styles[i][:2]][i] + (spacing if same_span else 0)
        count += 1
    return lines, max(widest, cur)


def tight_width(el: dict, size: float, width: float, base: tuple | None = None) -> float:
    """Narrowest box width that keeps the converter's wrapping unchanged.

    Every line's wrap width including its breaking space must still fit, and
    the painted ink must fit too. Narrowing never adds breaks, so the copy
    paints identically, only inside a box that hugs it.
    """
    return _tight_key(_key(el, size, base), float(width))


@lru_cache(maxsize=65_536)
def _tight_key(key, width):
    tokens, prefix, changes, spacing = _prepared(*key)
    lines, extents = _wrap(tokens, width)
    widest = max(_painted(line, prefix, changes, spacing) for line in lines)
    return min(width, max(max(extents), widest) + WRAP_SLACK)


def text_height(el: dict, size: float, lines: int) -> float:
    return lines * size * float(el.get("line_height", 1.2))


def fit_text(el: dict, width: float, max_h: float, max_size: float) -> tuple[int, float]:
    """Largest integer font size <= max_size whose wrapped text fits width x max_h.

    Returns (size, needed_height). Falls back to 1px if nothing fits.
    """

    def fits(size: int) -> tuple[bool, float]:
        lines, widest = measure(el, size, width)
        h = text_height(el, size, lines)
        return widest <= width and h <= max_h, h

    hi = paint_size(max_size)
    ok, h = fits(hi)
    if ok:
        return hi, h
    lo = 1
    if not fits(lo)[0]:
        return 1, fits(lo)[1]
    while hi - lo > 1:  # fits(lo) and not fits(hi)
        mid = (lo + hi) // 2
        if fits(mid)[0]:
            lo = mid
        else:
            hi = mid
    return lo, fits(lo)[1]
