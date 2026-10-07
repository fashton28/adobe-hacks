"""Reference pipeline: uniform scale, centered, no recomposition.

Everything keeps its relative arrangement (scaled by min(sx, sy) and centered),
backgrounds fill the canvas, decorations are clamped on-canvas. Never stretches,
always structurally valid; used as the fallback for smarter pipelines.
"""

from typing import Any

from pipelines.common.units import build_units, copy_design, place_bg, place_decor, place_rigid


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    W, H = target_canvas["width"], target_canvas["height"]
    Ws, Hs = source["canvas"]["width"], source["canvas"]["height"]
    s = min(W / Ws, H / Hs)
    ox, oy = (W - Ws * s) / 2, (H - Hs * s) / 2

    out = copy_design(source, target_canvas)
    for u in build_units(source):
        if u["kind"] == "bg":
            place_bg(out, u)
        elif u["kind"] == "decor":
            place_decor(out, source, u, s)
        else:
            x0, y0, _, _ = u["bbox"]
            place_rigid(out, source, u, s, ox + x0 * s, oy + y0 * s)
    return out
