"""Grouping of source elements into layout units, and helpers to place them.

Unit kinds:
  bg      backdrop: an unrotated, ungrouped cover image or any shape (solid
          fill, paper sheet, translucent scrim) covering most of the source
          canvas -> stretched to the full target canvas
  panel   ungrouped unrotated rectangle/line that frames part of the canvas
          (an edge band, a border, or an inset sheet behind copy) -> mapped
          to the corresponding region of the target canvas
  decor   ungrouped translucent / bleeding shape -> anchored to its relative
          spot, or, when it surrounds one content unit (a glow behind a
          product), it follows that unit (`follow` holds the unit's index)
  text    ungrouped text element -> re-fitted (font size + wrapping)
  rigid   images and explicit groups -> uniformly scaled + translated as one

Rigid units that repeat (same member types, similar size, aligned in the
source, like three product cards or a row of pills) share a `set` id so the
layout keeps them together in an even grid.
"""

import copy
import re

from .geometry import aabb, union
from .validate import is_background

BACKDROP_COVER = 0.85  # fraction of the source canvas a backdrop covers
PANEL_COVER = 0.25  # inset sheets behind most of the copy
BAND_SPAN = 0.9  # edge bands span this fraction of one canvas side
EDGE = 0.02  # "touches the edge" tolerance, as a fraction of that side
FOLLOW_AREA = 4.0  # a following decoration is at most this many times the unit's area


def ink_box(el: dict) -> tuple[float, float, float, float]:
    """Painted bounds: transparent padding of art and empty text box space do not count.

    Layout sizes and collision checks use what is actually visible; the full
    element box may overlap neighbours where it only holds transparent pixels.
    Text keeps its box height (line boxes are painted top-down) but only the
    width of its widest painted line, placed by its alignment. Rotated or
    missing artwork falls back to the element's bounds.
    """
    from .assets import asset_info
    from .text import measure, text_height

    box = aabb(el)
    if el.get("rotation", 0) or el["width"] <= 0 or el["height"] <= 0:
        return box
    if el["type"] == "text":
        lines, widest = measure(el, el["font_size"], el["width"])
        widest = min(el["width"], widest)
        height = min(el["height"], text_height(el, el["font_size"], lines))
        align = el.get("text_align", "left")
        x0 = el["x"] + {"left": 0.0, "right": el["width"] - widest}.get(align, (el["width"] - widest) / 2)
        return x0, el["y"], x0 + widest, el["y"] + height
    if el["type"] != "image":
        return box
    info = asset_info(el["asset_id"])
    if not info["available"] or not info["visible_bounds"]:
        return box
    vx0, vy0, vx1, vy1 = info["visible_bounds"]
    sx, sy = el["width"] / info["width"], el["height"] / info["height"]
    fit = el.get("fit", "contain")
    if fit in ("contain", "cover"):
        sx = sy = min(sx, sy) if fit == "contain" else max(sx, sy)
    dx, dy = (el["width"] - info["width"] * sx) / 2, (el["height"] - info["height"] * sy) / 2
    x0, y0 = max(0.0, dx + vx0 * sx), max(0.0, dy + vy0 * sy)
    x1, y1 = min(el["width"], dx + vx1 * sx), min(el["height"], dy + vy1 * sy)
    if x1 <= x0 or y1 <= y0:
        return box
    return el["x"] + x0, el["y"] + y0, el["x"] + x1, el["y"] + y1


def coverage(box, canvas) -> float:
    """Fraction of the canvas covered by an axis-aligned box."""
    x0, y0, x1, y1 = box
    w = max(0.0, min(x1, canvas["width"]) - max(x0, 0.0))
    h = max(0.0, min(y1, canvas["height"]) - max(y0, 0.0))
    return w * h / (canvas["width"] * canvas["height"])


def fill_alpha(el: dict) -> float:
    match = re.match(r"\s*rgba\s*\(([^)]*)\)", str(el.get("fill_color", "")))
    if match:
        parts = match.group(1).split(",")
        if len(parts) == 4:
            try:
                return float(parts[3])
            except ValueError:
                return 1.0
    return 1.0


def is_backdrop(el: dict, canvas: dict) -> bool:
    """Backdrops may stretch: shapes of any kind, and cover images (which crop)."""
    if el.get("group_id") or el.get("rotation", 0):
        return False
    if el["type"] == "image":
        return is_background(el, canvas)
    return el["type"] == "shape" and coverage(aabb(el), canvas) >= BACKDROP_COVER


def _band(el: dict, canvas: dict) -> bool:
    """A rectangle/line spanning one side of the canvas along an edge."""
    x0, y0, x1, y1 = aabb(el)
    W, H = canvas["width"], canvas["height"]
    wide = min(x1, W) - max(x0, 0) >= BAND_SPAN * W
    tall = min(y1, H) - max(y0, 0) >= BAND_SPAN * H
    return ((wide and (y0 <= EDGE * H or y1 >= (1 - EDGE) * H))
            or (tall and (x0 <= EDGE * W or x1 >= (1 - EDGE) * W)))


def _inside(inner, outer, slack=0.0) -> bool:
    return (inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack
            and inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack)


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _signature(source, u):
    return tuple(sorted((source["elements"][i]["type"], source["elements"][i].get("shape_type", ""))
                        for i in u["idx"]))


def _similar(a, b, source) -> bool:
    if _signature(source, a) != _signature(source, b):
        return False
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["bbox"], b["bbox"]
    aw, ah, bw, bh = ax1 - ax0, ay1 - ay0, bx1 - bx0, by1 - by0
    if min(aw, ah, bw, bh) <= 0:
        return False
    if max(ah, bh) > 1.15 * min(ah, bh) or max(aw, bw) > 1.4 * min(aw, bw):
        return False
    same_row = abs((ay0 + ay1) - (by0 + by1)) / 2 <= 0.25 * min(ah, bh)
    same_col = abs((ax0 + ax1) - (bx0 + bx1)) / 2 <= 0.25 * min(aw, bw)
    return same_row or same_col


def _assign_sets(source, units):
    """Union rigid units that repeat (cards, pills) into deterministic sets."""
    rigid = [u for u in units if u["kind"] == "rigid"]
    parent = {id(u): u for u in rigid}

    def find(u):
        while parent[id(u)] is not u:
            u = parent[id(u)]
        return u

    for i, a in enumerate(rigid):
        for b in rigid[i + 1:]:
            if _similar(a, b, source):
                ra, rb = find(a), find(b)
                if ra is not rb:
                    parent[id(rb)] = ra
    members = {}
    for u in rigid:
        members.setdefault(id(find(u)), []).append(u)
    for group in members.values():
        if len(group) < 2:
            continue
        key = min(min(u["idx"]) for u in group)
        for u in group:
            u["set"] = key


def build_units(source: dict) -> list[dict]:
    els, canvas = source["elements"], source["canvas"]
    by_group: dict[str, list[int]] = {}
    units = []
    for i, el in enumerate(els):
        gid = el.get("group_id")
        if gid:
            by_group.setdefault(gid, []).append(i)
        else:
            units.append({"idx": [i]})
    units += [{"idx": idx} for idx in by_group.values()]

    for u in units:
        members = [els[i] for i in u["idx"]]
        u["bbox"] = union(aabb(m) for m in members)
        u["ink"] = union(ink_box(m) for m in members)
        if len(members) == 1:
            m = members[0]
            x0, y0, x1, y1 = u["bbox"]
            bleeds = x0 < 0 or y0 < 0 or x1 > canvas["width"] or y1 > canvas["height"]
            translucent = m.get("opacity", 1) < 1 or fill_alpha(m) < 1
            if is_backdrop(m, canvas):
                u["kind"] = "bg"
            elif m["type"] == "text":
                u["kind"] = "text"
            elif (m["type"] == "shape" and not m.get("rotation", 0)
                  and m.get("shape_type") in ("rectangle", "line") and _band(m, canvas)):
                u["kind"], u["panel"] = "panel", "band"
            elif m["type"] == "shape" and (bleeds or translucent and m.get("shape_type") != "line"):
                # Rules and dividers stay structural even when tinted.
                u["kind"] = "decor"
            else:
                u["kind"] = "rigid"
        else:
            u["kind"] = "rigid"
        u["art"] = u["kind"] == "rigid" and all(m["type"] != "text" for m in members)
        u["images_only"] = u["art"] and all(m["type"] == "image" for m in members)

    content = [u for u in units if u["kind"] in ("text", "rigid")]
    # An opaque, unrotated rectangle that sits behind most of the copy is an
    # inset sheet (a card or paper panel), not a foreground box.
    for u in units:
        m = els[u["idx"][0]]
        if (u["kind"] != "rigid" or len(u["idx"]) > 1 or m["type"] != "shape" or m.get("rotation", 0)
                or m.get("shape_type") != "rectangle" or coverage(u["bbox"], canvas) < PANEL_COVER):
            continue
        z = m.get("z_index", u["idx"][0])
        covered = [v for v in content if v is not u and _inside(v["bbox"], u["bbox"], 1.0)
                   and els[v["idx"][0]].get("z_index", v["idx"][0]) >= z]
        if len(covered) >= 2:
            u["kind"], u["panel"] = "panel", "sheet"
    content = [u for u in units if u["kind"] in ("text", "rigid")]
    # A translucent shape wrapped tightly around one content unit (a glow or
    # halo behind a product) travels with that unit instead of the canvas.
    for u in units:
        if u["kind"] != "decor":
            continue
        x0, y0, x1, y1 = u["bbox"]
        if x0 < 0 or y0 < 0 or x1 > canvas["width"] or y1 > canvas["height"]:
            continue
        best = None
        for j, v in enumerate(units):
            if v["kind"] not in ("text", "rigid"):
                continue
            inner = _area(v["bbox"])
            if inner <= 0 or _area(u["bbox"]) > FOLLOW_AREA * inner:
                continue
            ox = max(0.0, min(x1, v["bbox"][2]) - max(x0, v["bbox"][0]))
            oy = max(0.0, min(y1, v["bbox"][3]) - max(y0, v["bbox"][1]))
            share = ox * oy / inner
            if share >= 0.6 and (best is None or share > best[0]):
                best = (share, j)
        if best is not None:
            u["follow"] = best[1]
    _assign_sets(source, units)
    return units


def copy_design(source: dict, target: dict) -> dict:
    return {
        "canvas": {"width": target["width"], "height": target["height"]},
        "elements": copy.deepcopy(source["elements"]),
    }


def place_rigid(out: dict, src: dict, unit: dict, s: float, tx: float, ty: float, origin: str = "bbox") -> None:
    """Scale the unit by `s` about the top-left of `unit[origin]` and move that corner to (tx, ty).

    Group labels are painted at an integer size no larger than their scaled
    box allows, so measurement and painting agree.
    """
    from .text import paint_size

    x0, y0, _, _ = unit[origin]
    for i in unit["idx"]:
        m, o = src["elements"][i], out["elements"][i]
        cx = tx + (m["x"] + m["width"] / 2 - x0) * s
        cy = ty + (m["y"] + m["height"] / 2 - y0) * s
        o["width"], o["height"] = m["width"] * s, m["height"] * s
        o["x"], o["y"] = cx - o["width"] / 2, cy - o["height"] / 2
        if m["type"] == "text":
            o["font_size"] = paint_size(m["font_size"] * s)
            if m.get("letter_spacing"):
                o["letter_spacing"] = m["letter_spacing"] * (o["font_size"] / m["font_size"])
        elif m["type"] == "shape":
            for key in ("corner_radius", "stroke_width"):
                if m.get(key):
                    o[key] = m[key] * s


def clamp_unit(out: dict, unit: dict) -> None:
    """Translate all members together so rotated bounds stay on canvas."""
    x0, y0, x1, y1 = union(aabb(out["elements"][i]) for i in unit["idx"])
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    dx = max(0, -x0) - max(0, x1 - W)
    dy = max(0, -y0) - max(0, y1 - H)
    for i in unit["idx"]:
        out["elements"][i]["x"] += dx
        out["elements"][i]["y"] += dy


def place_bg(out: dict, unit: dict) -> None:
    o = out["elements"][unit["idx"][0]]
    o["x"], o["y"] = 0, 0
    o["width"], o["height"] = out["canvas"]["width"], out["canvas"]["height"]


def panel_box(src: dict, unit: dict, W: float, H: float) -> tuple[float, float, float, float]:
    """Target box for a frame; edges stay on their edges.

    Sheets map proportionally on both axes, keeping relative margins. Bands
    stretch along the side they span; their thickness follows the uniform
    canvas scale and they stay on the edge they touched.
    """
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    s = min(W / Ws, H / Hs)
    x0, y0, x1, y1 = unit["bbox"]
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(Ws, x1), min(Hs, y1)
    box = [x0 / Ws * W, y0 / Hs * H, x1 / Ws * W, y1 / Hs * H]
    if unit.get("panel") == "band":
        for axis, (a0, a1, side, size) in enumerate(((x0, x1, Ws, W), (y0, y1, Hs, H))):
            if a1 - a0 >= BAND_SPAN * side:
                continue
            thick = min((a1 - a0) * s, size)
            if a0 <= EDGE * side:
                lo = 0.0
            elif a1 >= (1 - EDGE) * side:
                lo = size - thick
            else:
                lo = (box[axis] + box[axis + 2] - thick) / 2
            box[axis], box[axis + 2] = lo, lo + thick
    return tuple(box)


def place_panel(out: dict, src: dict, unit: dict) -> None:
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    s = min(W / src["canvas"]["width"], H / src["canvas"]["height"])
    m, o = src["elements"][unit["idx"][0]], out["elements"][unit["idx"][0]]
    x0, y0, x1, y1 = panel_box(src, unit, W, H)
    o["x"], o["y"], o["width"], o["height"] = x0, y0, x1 - x0, y1 - y0
    for key in ("corner_radius", "stroke_width"):
        if m.get(key):
            o[key] = m[key] * s


def place_decor(out: dict, src: dict, unit: dict, s: float) -> None:
    """Keep the decoration's relative anchor on the canvas, scaled by `s`, and clamp it on-canvas."""
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    x0, y0, x1, y1 = unit["bbox"]
    bw, bh = (x1 - x0) * s, (y1 - y0) * s
    s2 = min(1.0, W / bw if bw else 1.0, H / bh if bh else 1.0)
    s *= s2
    bw, bh = bw * s2, bh * s2
    cx, cy = (x0 + x1) / 2 / Ws * W, (y0 + y1) / 2 / Hs * H
    tx = min(max(cx - bw / 2, 0), W - bw)
    ty = min(max(cy - bh / 2, 0), H - bh)
    place_rigid(out, src, unit, s, tx, ty)


def place_follower(out: dict, src: dict, unit: dict, leader: dict) -> None:
    """Move a decoration with the content unit it surrounds (already placed in `out`)."""
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    lx0, ly0, lx1, ly1 = leader["bbox"]
    nx0, ny0, nx1, ny1 = union(aabb(out["elements"][i]) for i in leader["idx"])
    s = min((nx1 - nx0) / max(lx1 - lx0, 1e-9), (ny1 - ny0) / max(ly1 - ly0, 1e-9))
    x0, y0, x1, y1 = unit["bbox"]
    bw, bh = (x1 - x0) * s, (y1 - y0) * s
    shrink = min(1.0, W / bw if bw else 1.0, H / bh if bh else 1.0)
    s *= shrink
    bw, bh = bw * shrink, bh * shrink
    # Keep the decoration's centre offset from the leader's centre, scaled.
    cx = (nx0 + nx1) / 2 + ((x0 + x1) / 2 - (lx0 + lx1) / 2) * s
    cy = (ny0 + ny1) / 2 + ((y0 + y1) / 2 - (ly0 + ly1) / 2) * s
    tx = min(max(cx - bw / 2, 0), W - bw)
    ty = min(max(cy - bh / 2, 0), H - bh)
    place_rigid(out, src, unit, s, tx, ty)


def place_extras(out: dict, src: dict, units: list[dict], s: float) -> None:
    """Place backdrops, panels and decorations once content is in `out`."""
    for u in units:
        if u["kind"] == "bg":
            place_bg(out, u)
        elif u["kind"] == "panel":
            place_panel(out, src, u)
        elif u["kind"] == "decor":
            leader = units[u["follow"]] if "follow" in u else None
            if leader is not None and leader["kind"] in ("text", "rigid"):
                place_follower(out, src, u, leader)
            else:
                place_decor(out, src, u, s)
