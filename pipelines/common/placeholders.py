"""Placement policy for image units whose packaged asset is missing.

The official renderer paints a missing asset as an opaque, labeled grey
placeholder box, so it is visible in the scored PNG. Such a unit must stay in
the output (same id, same asset_id, on-canvas, aspect ratio preserved), but it
carries no artwork worth featuring. Policy:

* it never takes space in the content rows (layout generators defer it);
* when an opaque button or panel is painted above it, it is tucked fully
  underneath (scaled to fit well inside), so the placeholder never shows;
* otherwise it keeps its source-relative scale, capped by the uniform canvas
  scale, at the smallest of a few factors that keeps a MIN_SIDE floor, and
  moves as one rigid unit to the free spot nearest its source anchor that
  does not touch any content unit; larger sizes are used only when they save
  enough drift; if nothing is free, the least-overlapping spot wins and the
  overlap is reported by quality.metrics like any other.

Everything is deterministic: candidate spots are a fixed grid ordered by
distance to the anchor with stable tie-breaking.
"""

import math

from .assets import unavailable_unit
from .geometry import aabb, overlap_area, union
from .units import EXTRAS, build_units, place_rigid

SCALES = (0.25, 0.35, 0.5, 0.75, 1.0)  # ascending: a placeholder should be unobtrusive
GRID = 16
MIN_SIDE = 6.0
SIZE_WEIGHT = 0.25  # doubling the size costs as much as drifting ~17% of the diagonal


def missing_units(source: dict) -> list[dict]:
    return [u for u in build_units(source)
            if u["kind"] not in EXTRAS and unavailable_unit(source, u)]


def _spots(W, H, bw, bh, margin, anchor):
    """Top-left candidates inside the margin, nearest to the anchor first."""
    x_hi, y_hi = W - margin - bw, H - margin - bh
    xs = [margin + (x_hi - margin) * i / GRID for i in range(GRID + 1)]
    ys = [margin + (y_hi - margin) * j / GRID for j in range(GRID + 1)]
    ax = min(max(anchor[0] - bw / 2, margin), x_hi)
    ay = min(max(anchor[1] - bh / 2, margin), y_hi)
    spots = {(x, y) for x in xs for y in ys} | {(ax, ay)}
    return sorted(spots, key=lambda p: (math.hypot(p[0] - ax, p[1] - ay), p[1], p[0]))


def _hits(box, obstacles):
    x0, y0, x1, y1 = box
    return any(x0 < o[2] and o[0] < x1 and y0 < o[3] and o[1] < y1 for o in obstacles)


def _best_spot(W, H, sw, sh, fit, margin, gap, anchor, obstacles):
    """Return (scale, x, y) for a unit of source size sw x sh.

    The smallest size that keeps MIN_SIDE wins; larger sizes are only used
    when they cost less drift than they add in size (SIZE_WEIGHT), so the
    placeholder stays as unobtrusive as the contract allows.
    """
    diag = math.hypot(W, H)
    options = []
    for factor in SCALES:  # ascending sizes
        s = fit * factor
        if min(sw, sh) * s < MIN_SIDE and factor != SCALES[-1]:
            continue
        options.append((factor, s, _spots(W, H, sw * s, sh * s, margin, anchor)))
    best, best_key = None, math.inf
    for factor, s, spots in options:
        penalty = SIZE_WEIGHT * math.log(factor / options[0][0])
        if penalty >= best_key:
            break
        bw, bh = sw * s, sh * s
        for x, y in spots:  # Nearest first: the first free spot is optimal.
            if not _hits((x - gap, y - gap, x + bw + gap, y + bh + gap), obstacles):
                key = penalty + math.hypot(x + bw / 2 - anchor[0], y + bh / 2 - anchor[1]) / diag
                if key < best_key:
                    best, best_key = (s, x, y), key
                break
    if best is not None:
        return best
    # Nothing is free: take the least-overlapping spot (smallest size first).
    fallback = None
    for factor, s, spots in options:
        bw, bh = sw * s, sh * s
        for x, y in spots:
            area = sum(overlap_area((x, y, x + bw, y + bh), o) for o in obstacles)
            if fallback is None or area < fallback[0]:
                fallback = (area, (s, x, y))
    return fallback[1]


TUCK_INSET = 0.1  # a tucked placeholder keeps this share of the cover's size clear on each side


def _covers(out: dict, source: dict, z: float, missing_idx: set) -> list:
    """Boxes of opaque, unrotated shapes painted above paint order `z` (buttons, panels)."""
    from .units import fill_alpha

    boxes = []
    by_id = {el["id"]: el for el in out["elements"]}
    for i, m in enumerate(source["elements"]):
        if i in missing_idx or m["type"] != "shape" or m.get("rotation", 0):
            continue
        if fill_alpha(m) < 1 or m.get("opacity", 1) < 1 or m.get("z_index", i) <= z:
            continue
        if m.get("shape_type") not in ("rectangle", "ellipse"):
            continue
        boxes.append(aabb(by_id[m["id"]]))
    return boxes


def _tuck(sw, sh, covers, anchor):
    """(scale, x, y) hiding a sw x sh unit fully under the nearest opaque cover, or None."""
    best = None
    for x0, y0, x1, y1 in covers:
        w, h = (x1 - x0) * (1 - 2 * TUCK_INSET), (y1 - y0) * (1 - 2 * TUCK_INSET)
        s = min(w / sw, h / sh)
        if min(sw, sh) * s < 1:
            continue
        # An ellipse hides only its inscribed rectangle: stay well inside.
        s *= 0.7
        bw, bh = sw * s, sh * s
        x, y = (x0 + x1 - bw) / 2, (y0 + y1 - bh) / 2
        d = math.hypot(x + bw / 2 - anchor[0], y + bh / 2 - anchor[1])
        if best is None or d < best[0]:
            best = (d, (s, x, y))
    return None if best is None else best[1]


def place_missing_assets(out: dict, source: dict) -> dict:
    """Relocate fully-missing image units in `out` (mutated and returned)."""
    missing = missing_units(source)
    if not missing:
        return out
    missing_idx = {i for u in missing for i in u["idx"]}
    by_id = {el["id"]: el for el in out["elements"]}
    obstacles = [union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"])
                 for u in build_units(source)
                 if u["kind"] not in EXTRAS and not set(u["idx"]) & missing_idx]
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    Ws, Hs = source["canvas"]["width"], source["canvas"]["height"]
    base = min(W / Ws, H / Hs)
    margin = min(W, H) * 0.025
    gap = min(W, H) * 0.02
    # place_rigid indexes `out` like `source`; work on an aligned view.
    aligned = {"canvas": out["canvas"],
               "elements": [by_id[el["id"]] for el in source["elements"]]}
    for u in missing:
        x0, y0, x1, y1 = u["bbox"]
        sw, sh = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        fit = min(base, (W - 2 * margin) / sw, (H - 2 * margin) / sh)
        anchor = ((x0 + x1) / 2 / Ws * W, (y0 + y1) / 2 / Hs * H)
        # The renderer paints a missing asset as a red-outlined box: hide it
        # under an opaque button or panel painted above it when one exists,
        # else use the smallest legal size in free space.
        z = max(source["elements"][i].get("z_index", i) for i in u["idx"])
        tucked = _tuck(sw, sh, _covers(out, source, z, missing_idx), anchor)
        best = tucked or _best_spot(W, H, sw, sh, fit, margin, gap, anchor, obstacles)
        s, x, y = best
        place_rigid(aligned, source, u, s, x, y)
        obstacles.append(union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"]))
    return out
