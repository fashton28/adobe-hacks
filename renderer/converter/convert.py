"""CHAMELEON design schema (v0.9) -> Crello v5 normalized/encoded example.

`convert_chameleon_to_crello` accepts either shape the engine hands it:
- the flat `{"canvas": ..., "elements": [...]}` design object (schema
  v0.9 - what `engine/main.py` passes to the renderer for both the source
  design and `resize()`'s output), or
- an older `{"source": {"canvas": ..., "elements": [...]}, ...}` wrapper,
  for backward compatibility with the original sample-task files.

`render_design_to_png` is the integration entry point `engine/main.py`
looks for (`renderer.converter.convert.render_design_to_png`) - it wires
the conversion above to a brand-kit-backed `CrelloV5Renderer` and writes
the result straight to a PNG file.
"""

import logging
from itertools import accumulate
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

from cr_renderer import CrelloV5Renderer
from cr_renderer.fonts import FONT_WEIGHTS

from .assets import asset_path, load_asset_image
from .brand_fonts import load_brand_font_manager
from .colorutil import parse_rgba
from .features_stub import make_stub_features
from .shapes import render_shape, shape_fill_alpha
from .wrap import char_widths, wrap_text

logger = logging.getLogger(__name__)

_BLANK_IMAGE = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
_DEFAULT_LINE_HEIGHT = 1.2
_BOLD_WEIGHTS = {"bold", "semibold", "extrabold", "black"}


def convert_chameleon_to_crello(
    doc: Dict[str, Any],
    font_manager,
    assets_dir: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Convert a CHAMELEON design document to a Crello v5 example.

    `font_manager` is a `cr_renderer.fonts.FontManager` instance, reused
    from the renderer so text-wrap width measurements use the exact same
    font lookups/fallbacks that will later render the glyphs.
    """
    design = doc["source"] if "source" in doc else doc
    canvas = design["canvas"]
    canvas_width = float(canvas["width"])
    canvas_height = float(canvas["height"])
    elements = sorted(design["elements"], key=lambda e: e.get("z_index", 0))

    out: Dict[str, Any] = {
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "length": len(elements),
        "left": [],
        "top": [],
        "width": [],
        "height": [],
        "angle": [],
        "type": [],
        "color": [],
        "opacity": [],
        "text": [],
        "font_size": [],
        "font": [],
        "line_height": [],
        "text_align": [],
        "capitalize": [],
        "letter_spacing": [],
        "font_bold": [],
        "font_italic": [],
        "text_color": [],
        "text_line": [],
        "image": [],
    }
    warnings: List[str] = []

    for element in elements:
        etype = element.get("type")
        eid = element.get("id", "?")

        out["left"].append(float(element.get("x", 0.0)))
        out["top"].append(float(element.get("y", 0.0)))
        out["width"].append(float(element.get("width", 1.0)))
        out["height"].append(float(element.get("height", 1.0)))
        out["angle"].append(float(element.get("rotation", 0.0)))
        out["opacity"].append(float(element.get("opacity", 1.0)))
        out["color"].append([])

        if etype == "text":
            out["type"].append("TextElement")
            _append_text(out, element, font_manager)
            out["image"].append(_BLANK_IMAGE)
        elif etype == "shape":
            out["type"].append("ImageElement")
            _append_blank_text(out)
            out["opacity"][-1] *= shape_fill_alpha(element)
            out["image"].append(render_shape(element))
        elif etype == "image":
            out["type"].append("ImageElement")
            _append_blank_text(out)
            asset_id = element.get("asset_id")
            if asset_id and asset_path(assets_dir, asset_id) is None:
                warnings.append(
                    f"Missing asset '{asset_id}' for element '{eid}' - rendered a placeholder."
                )
            out["image"].append(
                load_asset_image(
                    assets_dir,
                    asset_id,
                    element.get("width", 1.0),
                    element.get("height", 1.0),
                    element.get("fit", "contain"),
                )
            )
        else:
            warnings.append(f"Unknown element type '{etype}' for '{eid}' - skipped (blank).")
            out["type"].append("ImageElement")
            _append_blank_text(out)
            w = max(1, round(element.get("width", 1.0)))
            h = max(1, round(element.get("height", 1.0)))
            out["image"].append(Image.new("RGBA", (w, h), (0, 0, 0, 0)))

    return out, warnings


def _append_blank_text(out: Dict[str, Any]) -> None:
    """Fill the text-only columns with inert defaults for a non-text element."""
    out["text"].append("")
    out["font_size"].append(1.0)
    out["font"].append("")
    out["line_height"].append(1.0)
    out["text_align"].append("left")
    out["capitalize"].append(False)
    out["letter_spacing"].append(0.0)
    out["font_bold"].append([])
    out["font_italic"].append([])
    out["text_color"].append([])
    out["text_line"].append([])


def _is_italic(value: Optional[Union[str, bool]]) -> bool:
    """Accepts either the v0.9 schema's `font_style: "normal"/"italic"` or a
    plain boolean `italic` flag, for flexibility across schema revisions."""
    if isinstance(value, bool):
        return value
    return value == "italic"


def _append_text(out: Dict[str, Any], element: Dict[str, Any], font_manager) -> None:
    content = str(element.get("content", ""))
    family = element.get("font_family", "Montserrat")
    size = float(element.get("font_size", 24))
    weight = _normalize_weight(element.get("font_weight"))
    is_bold = weight in _BOLD_WEIGHTS
    is_italic = _is_italic(element.get("font_style") or element.get("italic"))
    style = _weight_style_to_font_style(is_bold, is_italic)

    widths = char_widths(font_manager, family, weight, style, size, content)
    wrapped = wrap_text(content, widths, float(element.get("width", 1.0)))
    n = len(wrapped)

    default_color = element.get("color", "rgba(0,0,0,1)")
    bold_flags = [weight in _BOLD_WEIGHTS] * n
    italic_flags = [style in ("italic", "bolditalic")] * n
    colors = [default_color] * n

    for run in element.get("style_runs") or []:
        start = max(0, int(run.get("start", 0)))
        end = min(n - 1, int(run.get("end", n - 1)))
        if start > end:
            continue
        if "color" in run:
            for i in range(start, end + 1):
                colors[i] = run["color"]
        if "font_weight" in run:
            run_bold = _normalize_weight(run.get("font_weight")) in _BOLD_WEIGHTS
            for i in range(start, end + 1):
                bold_flags[i] = run_bold
        if "font_style" in run or "italic" in run:
            run_italic = _is_italic(run.get("font_style") or run.get("italic"))
            for i in range(start, end + 1):
                italic_flags[i] = run_italic

    text_line = list(accumulate(int(c == "\n") for c in wrapped))

    out["text"].append(wrapped)
    out["font_size"].append(size)
    out["font"].append(family)
    out["line_height"].append(float(element.get("line_height", _DEFAULT_LINE_HEIGHT)))
    out["text_align"].append(element.get("text_align", "left"))
    out["capitalize"].append(bool(element.get("capitalize", False)))
    out["letter_spacing"].append(float(element.get("letter_spacing", 0.0)))
    out["font_bold"].append(bold_flags)
    out["font_italic"].append(italic_flags)
    out["text_color"].append(colors)
    out["text_line"].append(text_line)


def _normalize_weight(weight: Optional[str]) -> str:
    if not weight:
        return "regular"
    weight = weight.lower()
    return weight if weight in FONT_WEIGHTS else "regular"


def _weight_style_to_font_style(is_bold: bool, is_italic: bool) -> str:
    """Mirror cr_renderer.text_utils.make_text_blob's own weight/style
    derivation, so the font used to *measure* wrap widths matches the font
    that will actually be *rendered* (cr-renderer recomputes this itself at
    render time from the bold/italic per-character maps - if this measuring
    step used a different rule, it would just cause wrap widths to be
    measured against the wrong font)."""
    if is_bold and is_italic:
        return "bolditalic"
    if is_bold:
        return "bold"
    if is_italic:
        return "italic"
    return "regular"


# --------------------------------------------------------------------------
# Integration entry point for engine/main.py
# --------------------------------------------------------------------------

_STUB_FEATURES = make_stub_features()
_renderer_cache: Dict[str, CrelloV5Renderer] = {}


def _get_renderer(fonts_dir: str) -> CrelloV5Renderer:
    """Build (and cache, per fonts_dir) a `CrelloV5Renderer` backed by local
    brand-kit fonts - no network access, no `fonts.pickle` download."""
    renderer = _renderer_cache.get(fonts_dir)
    if renderer is None:
        renderer = CrelloV5Renderer.__new__(CrelloV5Renderer)
        renderer.features = _STUB_FEATURES
        renderer.font_manager = load_brand_font_manager(fonts_dir)
        _renderer_cache[fonts_dir] = renderer
    return renderer


def render_design_to_png(
    design: Dict[str, Any],
    assets_dir: Union[str, Path],
    png_path: Union[str, Path],
    fonts_dir: Optional[Union[str, Path]] = None,
    max_size: Optional[int] = None,
) -> List[str]:
    """Render a CHAMELEON design (flat `{"canvas", "elements"}` shape) to a
    PNG file. This is what `engine/main.py` calls
    (`renderer.converter.convert.render_design_to_png`).

    `fonts_dir` defaults to a `fonts/` folder next to `assets_dir` (i.e.
    `brand_kit/assets` + `brand_kit/fonts`), matching this repo's layout.
    Returns the list of conversion warnings (missing assets, unknown
    element types, etc.) for the caller to log.
    """
    assets_dir = str(assets_dir)
    fonts_dir = str(fonts_dir) if fonts_dir is not None else str(Path(assets_dir).parent / "fonts")

    renderer = _get_renderer(fonts_dir)
    example, warnings = convert_chameleon_to_crello(design, renderer.font_manager, assets_dir)
    image_bytes = renderer.render(example, max_size=max_size or 2048, format="png")
    Path(png_path).write_bytes(image_bytes)
    return warnings
