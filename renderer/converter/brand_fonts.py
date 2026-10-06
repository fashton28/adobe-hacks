"""Load a brand-kit fonts folder straight into a `cr_renderer.fonts.FontManager`.

The brand kit ships plain `.ttf`/`.otf` files named `<Family>-<Suffix>.ttf`
(e.g. `SolsticeSans-BoldItalic.ttf`), not the `fonts.pickle` cr-renderer's
`FontManager` normally downloads from Hugging Face. This module scans that
folder into the same in-memory shape `FontManager` uses internally
(`{normalized_family: [{"fontFamily", "fontWeight", "fontStyle", "bytes"}]}`)
and hands it to a `FontManager` instance directly - so lookups still go
through `FontManager.lookup()`'s existing weight/style fallback logic
unchanged, just without ever touching the network.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cr_renderer.fonts import FONT_WEIGHTS, FontManager, normalize_family

_CAMEL_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])")
_ITALIC_RE = re.compile("italic", re.IGNORECASE)
_FONT_EXTENSIONS = {".ttf", ".otf"}


def _split_family_suffix(stem: str) -> Tuple[str, str]:
    prefix, _, suffix = stem.partition("-")
    family = _CAMEL_SPLIT_RE.sub(" ", prefix).strip()
    return family, suffix


def _suffix_to_weight_style(suffix: str) -> Tuple[str, str]:
    suffix = suffix or "Regular"
    is_italic = bool(_ITALIC_RE.search(suffix))
    weight_token = _ITALIC_RE.sub("", suffix).strip().lower() or "regular"
    weight = weight_token if weight_token in FONT_WEIGHTS else "regular"
    if is_italic:
        style = "bolditalic" if weight == "bold" else "italic"
    else:
        style = "bold" if weight == "bold" else "regular"
    return weight, style


def build_font_dict(fonts_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """Scan a flat directory of brand-kit font files into a `FontDict`."""
    font_dict: Dict[str, List[Dict[str, Any]]] = {}
    for path in sorted(Path(fonts_dir).glob("*")):
        if path.suffix.lower() not in _FONT_EXTENSIONS:
            continue
        family, suffix = _split_family_suffix(path.stem)
        weight, style = _suffix_to_weight_style(suffix)
        key = normalize_family(family)
        font_dict.setdefault(key, []).append(
            {
                "fontFamily": family,
                "fontWeight": weight,
                "fontStyle": style,
                "bytes": path.read_bytes(),
            }
        )
    return font_dict


def load_brand_font_manager(fonts_dir: str) -> FontManager:
    """Build a `FontManager` populated from local brand-kit font files."""
    font_dict = build_font_dict(fonts_dir)
    if not font_dict:
        raise FileNotFoundError(f"No .ttf/.otf font files found in: {fonts_dir}")
    manager = FontManager.__new__(FontManager)
    manager._fonts = font_dict
    return manager
