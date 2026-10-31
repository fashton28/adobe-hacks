"""Placement policy for image units whose packaged asset is missing.

The official renderer paints a missing asset as an opaque, labeled grey
placeholder box, so it is visible in the scored PNG. Such a unit must stay in
the output (same id, same asset_id, on-canvas, aspect ratio preserved), but it
carries no artwork worth featuring. Policy:

* it never takes space in the content rows (layout generators defer it);
* it keeps its source-relative scale, capped by the uniform canvas scale;
* it is moved, as one rigid unit, to the free spot nearest its source anchor
  that does not touch any content unit (copy, art, buttons, badges);
* among collision-free spots it balances drift from the anchor against
  shrinking (down to a small floor); if nothing is free, the least-overlapping
  spot wins and the overlap is reported by quality.metrics like any other.

Everything is deterministic: candidate spots are a fixed grid ordered by
distance to the anchor with stable tie-breaking.
"""

import math

from .assets import unavailable_unit
from .geometry import aabb, overlap_area, union
from .units import build_units, place_rigid

SCALES = (1.0, 0.75, 0.5, 0.35, 0.25)
GRID = 16
MIN_SIDE = 6.0
SHRINK_WEIGHT = 0.25


def missing_units(source: dict) -> list[dict]:
    return [u for u in build_units(source)
            if u["kind"] not in ("bg", "decor", "panel") and unavailable_unit(source, u)]


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
    """Return (scale, x, y) for a unit of source size sw x sh."""
    diag = math.hypot(W, H)
    options = []
    for factor in SCALES:
        s = fit * factor
        if factor != SCALES[0] and min(sw, sh) * s < MIN_SIDE:
            break
        options.append((factor, s, _spots(W, H, sw * s, sh * s, margin, anchor)))
    best, best_key = None, math.inf
    for factor, s, spots in options:
        # Drift from the anchor (a canvas fraction) trades against shrinking:
        # halving the size costs as much as drifting ~17% of the diagonal.
        penalty = -SHRINK_WEIGHT * math.log(factor)
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
    for factor, s, spots in reversed(options):
        bw, bh = sw * s, sh * s
        for x, y in spots:
            area = sum(overlap_area((x, y, x + bw, y + bh), o) for o in obstacles)
            if fallback is None or area < fallback[0]:
                fallback = (area, (s, x, y))
    return fallback[1]


def place_missing_assets(out: dict, source: dict) -> dict:
    """Relocate fully-missing image units in `out` (mutated and returned)."""
    missing = missing_units(source)
    if not missing:
        return out
    missing_idx = {i for u in missing for i in u["idx"]}
    by_id = {el["id"]: el for el in out["elements"]}
    obstacles = [union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"])
                 for u in build_units(source)
                 if u["kind"] not in ("bg", "decor", "panel") and not set(u["idx"]) & missing_idx]
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
        best = _best_spot(W, H, sw, sh, fit, margin, gap, anchor, obstacles)
        s, x, y = best
        place_rigid(aligned, source, u, s, x, y)
        obstacles.append(union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"]))
    return out
