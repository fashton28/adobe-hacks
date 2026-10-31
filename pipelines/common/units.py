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

  bridge  small badge straddling two content units (a VS disc between two
          cards) -> placed after layout at the same relative spot between
          its hosts (`hosts` holds their indices)

Composites (round 4, fidelity): content painted inside a card, panel or badge
shape is merged into that shape's unit, recursively, so a form field and its
button stay in their card; overlapping artwork (a product in front of a sun
disc) forms one rigid motif; translucent rings centred on a motif follow it.

Rigid units that repeat (same member types, similar size, aligned in the
source, like three product cards or a row of pills) share a `set` id so the
layout keeps them together in an even grid.
"""

import copy
import math
import re

from .geometry import aabb, extent, union
from .validate import BAND_SPAN, EDGE, edge_band, is_background

EXTRAS = ("bg", "decor", "panel", "bridge")  # kinds placed around the content, not laid out
BACKDROP_COVER = 0.85  # fraction of the source canvas a backdrop covers
PANEL_COVER = 0.25  # inset sheets behind most of the copy
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


def _inside(inner, outer, slack=0.0) -> bool:
    return (inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack
            and inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack)


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _signature(source, u):
    """Member types of the unit's core (its own group, without merged stickers or contents)."""
    return tuple(sorted((source["elements"][i]["type"], source["elements"][i].get("shape_type", ""))
                        for i in u.get("core_idx", u["idx"])))


def _similar(a, b, source) -> bool:
    if _signature(source, a) != _signature(source, b):
        return False
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a.get("core_bbox", a["bbox"]), b.get("core_bbox", b["bbox"])
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
    for idx in by_group.values():
        # An edge band inside a group (a footer strip behind a logo) frames
        # the canvas: it becomes its own band, carrying the rest.
        bands = [i for i in idx if len(idx) > 1 and edge_band(els[i], canvas)]
        units += [{"idx": [i]} for i in bands]
        rest = [i for i in idx if i not in bands]
        if rest:
            units.append({"idx": rest})

    for u in units:
        members = [els[i] for i in u["idx"]]
        # The full extent (rotated bounds and unrotated box) is what must stay on canvas.
        u["bbox"] = union(extent(m) for m in members)
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
            elif edge_band(m, canvas):
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
    units = _attach_stickers(source, units)
    units = _merge_contained(source, units)
    units = _merge_motifs(source, units)
    _mark_bridges(source, units)
    # A translucent shape wrapped tightly around one content unit (a glow or
    # halo behind a product) travels with that unit instead of the canvas.
    # Rings centred on a unit follow it too, even when they bled off the
    # canvas, so a sun and its halo stay concentric.
    for u in units:
        if u["kind"] != "decor":
            continue
        x0, y0, x1, y1 = u["bbox"]
        bleeds = x0 < 0 or y0 < 0 or x1 > canvas["width"] or y1 > canvas["height"]
        best = None
        for j, v in enumerate(units):
            if v["kind"] not in ("text", "rigid"):
                continue
            vb = v.get("core_bbox", v["bbox"])  # a glow follows the product, not its sticker
            inner = _area(vb)
            if inner <= 0:
                continue
            ox = max(0.0, min(x1, vb[2]) - max(x0, vb[0]))
            oy = max(0.0, min(y1, vb[3]) - max(y0, vb[1]))
            share = ox * oy / inner
            ring = (v["art"] or v.get("core_art")) and _concentric(u["bbox"], v["bbox"])
            limit = RING_AREA if ring else FOLLOW_AREA
            if share < 0.6 or _area(u["bbox"]) > limit * inner or (bleeds and not ring):
                continue
            if best is None or share > best[0]:
                best = (share, j)
        if best is not None:
            u["follow"] = best[1]
    _assign_sets(source, units)
    _assign_carriers(source, units)
    return units


def _z(source, u) -> float:
    return min(source["elements"][i].get("z_index", i) for i in u["idx"])


STICKER_OVERLAP = (0.15, 0.95)  # share of a sticker's box lying on its host
STICKER_AREA = 0.5  # a sticker is at most this share of its host's area


def _attach_stickers(source, units):
    """Merge each sticker into the unit it overlaps (a badge on a product corner).

    A sticker is a rigid unit with a shape (a badge, stamp or tag group)
    whose box lies partly, not wholly, on a larger rigid unit below it. The
    merged unit moves and scales as one, so the callout stays attached at
    the same relative spot. The host's own members are kept as the `core`
    (artwork scale, followers and prominence follow the host only).
    """
    els = source["elements"]
    rigid = [u for u in units if u["kind"] == "rigid"]
    absorbed, hosts = set(), {}
    for a in sorted(rigid, key=lambda u: (_area(u["bbox"]), min(u["idx"]))):
        if not any(els[i]["type"] == "shape" for i in a["idx"]) or id(a) in hosts:
            continue
        best = None
        for b in rigid:
            if b is a or id(b) in absorbed or _area(a["bbox"]) > STICKER_AREA * _area(b["bbox"]):
                continue
            if _z(source, a) <= max(els[i].get("z_index", i) for i in b["idx"]):
                continue  # a sticker paints above its whole host
            ox = max(0.0, min(a["bbox"][2], b["bbox"][2]) - max(a["bbox"][0], b["bbox"][0]))
            oy = max(0.0, min(a["bbox"][3], b["bbox"][3]) - max(a["bbox"][1], b["bbox"][1]))
            share = ox * oy / max(_area(a["bbox"]), 1e-9)
            if STICKER_OVERLAP[0] <= share <= STICKER_OVERLAP[1] and (best is None or share > best[0]):
                best = (share, b)
        if best is not None:
            absorbed.add(id(a))
            hosts.setdefault(id(best[1]), (best[1], []))[1].append(a)
    if not hosts:
        return units
    merged = []
    for u in units:
        if id(u) in absorbed:
            continue
        if id(u) in hosts:
            host, stickers = hosts[id(u)]
            parts = [host, *stickers]
            u = {"idx": sorted(i for p in parts for i in p["idx"]), "kind": "rigid",
                 "bbox": union(p["bbox"] for p in parts), "ink": union(p["ink"] for p in parts),
                 "core_idx": list(host["idx"]), "core_bbox": host["bbox"], "core_ink": host["ink"],
                 "art": False, "images_only": False, "core_art": host["art"]}
        merged.append(u)
    return merged


CONTAIN = 0.85  # share of a unit's painted box inside a container shape that makes it content
MOTIF_OVERLAP = 0.25  # share of the smaller artwork's painted box overlapping another
RING_AREA = 16.0  # a concentric ring may be this many times its leader's area
RING_OFFSET = 0.2  # centre distance, share of the ring's short side, that still counts as concentric
BRIDGE_TOUCH = 0.02  # least share of a bridge's box lying on each of its hosts


def _order(source):
    """Paint position of each element (renderer: stable sort on z_index, default 0)."""
    els = source["elements"]
    ranked = sorted(range(len(els)), key=lambda i: (els[i].get("z_index", 0) or 0, i))
    return {i: n for n, i in enumerate(ranked)}


def _share_in(box, outer) -> float:
    w = min(box[2], outer[2]) - max(box[0], outer[0])
    h = min(box[3], outer[3]) - max(box[1], outer[1])
    return max(0.0, w) * max(0.0, h) / max(_area(box), 1e-9)


def _merged(host, parts, core_art=None):
    """One rigid unit made of `host` (kept as the core) and `parts`."""
    every = [host, *parts]
    core_idx = host.get("core_idx", host["idx"])
    return {"idx": sorted(i for p in every for i in p["idx"]), "kind": "rigid",
            "bbox": union(p["bbox"] for p in every), "ink": union(p["ink"] for p in every),
            "core_idx": list(core_idx), "core_bbox": host.get("core_bbox", host["bbox"]),
            "core_ink": host.get("core_ink", host["ink"]), "art": all(p["art"] for p in every),
            "images_only": all(p["images_only"] for p in every),
            "core_art": host.get("core_art", host["art"]) if core_art is None else core_art}


def _merge_contained(source, units):
    """Merge content painted inside a card, panel or badge shape into that shape's unit.

    A unit is content of a container when at least CONTAIN of its painted box
    lies inside a (non-line) shape of a rigid unit, every one of its members
    paints above that shape, and it is smaller than the shape. Innermost
    containers merge first, so nested cards compose recursively; the
    container's unit stays the core (its own group geometry and scale).
    """
    els = source["elements"]
    order = _order(source)
    while True:
        best = None
        for h, host in enumerate(units):
            if host["kind"] != "rigid":
                continue
            for c in host["idx"]:
                m = els[c]
                if m["type"] != "shape" or m.get("shape_type") == "line" or m["width"] <= 0 or m["height"] <= 0:
                    continue
                cb = aabb(m)
                for v, unit in enumerate(units):
                    if (v == h or unit["kind"] not in ("text", "rigid") or _area(unit["ink"]) >= _area(cb)
                            or min(order[i] for i in unit["idx"]) <= order[c]
                            or _share_in(unit["ink"], cb) < CONTAIN):
                        continue
                    key = (_area(cb), c, min(unit["idx"]))
                    if best is None or key < best[0]:
                        best = (key, h, v)
        if best is None:
            return units
        _, h, v = best
        merged = _merged(units[h], [units[v]])
        units = [merged if n == h else u for n, u in enumerate(units) if n != v]


def _merge_motifs(source, units):
    """Merge overlapping text-free artwork (a product in front of a sun disc) into one rigid motif.

    The largest image (or the larger unit) stays the core, so artwork
    prominence and followers keep referring to the product.
    """
    from .assets import unavailable_unit

    def candidate(u):
        return u["kind"] == "rigid" and u["art"] and not unavailable_unit(source, u)

    while True:
        pair = None
        for a in range(len(units)):
            if not candidate(units[a]):
                continue
            for b in range(a + 1, len(units)):
                if not candidate(units[b]):
                    continue
                ia, ib = units[a]["ink"], units[b]["ink"]
                small = ia if _area(ia) <= _area(ib) else ib
                big = ib if small is ia else ia
                if _share_in(small, big) >= MOTIF_OVERLAP:
                    pair = (a, b)
                    break
            if pair:
                break
        if pair is None:
            return units
        a, b = pair

        def weight(u):
            images = any(source["elements"][i]["type"] == "image" for i in u.get("core_idx", u["idx"]))
            return (images, _area(u.get("core_ink", u["ink"])), -min(u["idx"]))

        host, part = (units[a], units[b]) if weight(units[a]) >= weight(units[b]) else (units[b], units[a])
        merged = _merged(host, [part], core_art=True)
        units = [merged if n == a else u for n, u in enumerate(units) if n != b]


def _mark_bridges(source, units):
    """A small badge painted over the meeting point of two content units becomes a bridge.

    It overlaps both (BRIDGE_TOUCH of its box each), paints above them, is
    at most STICKER_AREA of each, and its centre lies between their centres.
    After layout it is put back at the same spot between its hosts.
    """
    els = source["elements"]
    for b in units:
        if b["kind"] != "rigid" or not any(els[i]["type"] == "shape" for i in b["idx"]):
            continue
        hosts = []
        for j, h in enumerate(units):
            if h is b or h["kind"] != "rigid" or _area(b["bbox"]) > STICKER_AREA * _area(h["bbox"]):
                continue
            if _share_in(b["bbox"], h.get("core_bbox", h["bbox"])) < BRIDGE_TOUCH or _z(source, b) <= max(
                    els[i].get("z_index", i) for i in h.get("core_idx", h["idx"])):
                continue
            hosts.append(j)
        if len(hosts) != 2:
            continue
        (a0, a1), (c0, c1) = _centre(units[hosts[0]]["bbox"]), _centre(units[hosts[1]]["bbox"])
        bx, by = _centre(b["bbox"])
        dx, dy = c0 - a0, c1 - a1
        t = ((bx - a0) * dx + (by - a1) * dy) / max(dx * dx + dy * dy, 1e-9)
        if 0.0 < t < 1.0:
            b["kind"], b["hosts"], b["between"] = "bridge", hosts, t


def _centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _concentric(ring, inner) -> bool:
    (rx, ry), (ix, iy) = _centre(ring), _centre(inner)
    short = min(ring[2] - ring[0], ring[3] - ring[1])
    return ((rx - ix) ** 2 + (ry - iy) ** 2) ** 0.5 <= RING_OFFSET * short


def _assign_carriers(source, units):
    """Panels (edge bands, sheets) record the content units sitting on them.

    A unit is carried when its centre lies on the panel and it paints above
    it: a white logo on a dark footer band, copy on a scrim. Layouts keep
    carried content inside its panel (contrast depends on it).
    """
    for p in units:
        if p["kind"] != "panel":
            continue
        px0, py0, px1, py1 = p["bbox"]
        z = _z(source, p)
        p["carries"] = [j for j, u in enumerate(units)
                        if u["kind"] in ("text", "rigid") and _z(source, u) >= z
                        and px0 <= (u["bbox"][0] + u["bbox"][2]) / 2 <= px1
                        and py0 <= (u["bbox"][1] + u["bbox"][3]) / 2 <= py1]


def copy_design(source: dict, target: dict) -> dict:
    """A fresh output design: the source elements on the target canvas.

    A non-positive text line height (schema-valid, rejected by the renderer)
    becomes 1.0, the value text measurement already assumes for it.
    """
    elements = copy.deepcopy(source["elements"])
    for el in elements:
        if el.get("type") == "text" and isinstance(el.get("line_height"), (int, float)) and el["line_height"] <= 0:
            el["line_height"] = 1.0
    return {"canvas": {"width": target["width"], "height": target["height"]}, "elements": elements}


MIN_TEXT_BOX = 1.0  # px: smallest text box side the official renderer accepts (it requires > 0)


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
            # The renderer rejects text boxes without area (schema-valid in a
            # source): such a box becomes MIN_TEXT_BOX px about the same centre.
            for size, pos in (("width", "x"), ("height", "y")):
                if o[size] <= 0:
                    o[pos] -= (MIN_TEXT_BOX - o[size]) / 2
                    o[size] = MIN_TEXT_BOX
            o["font_size"] = paint_size(m["font_size"] * s)
            if m.get("letter_spacing"):
                o["letter_spacing"] = m["letter_spacing"] * (o["font_size"] / m["font_size"])
        elif m["type"] == "shape":
            for key in ("corner_radius", "stroke_width"):
                if m.get(key):
                    o[key] = m[key] * s


def clamp_unit(out: dict, unit: dict) -> None:
    """Translate all members together so rotated bounds and unrotated boxes stay on canvas."""
    x0, y0, x1, y1 = union(extent(out["elements"][i]) for i in unit["idx"])
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
    raw = unit["bbox"]
    # Clamp each axis as an interval: a band lying wholly outside the source
    # canvas must not invert into a negative width or height.
    x0 = min(max(0.0, raw[0]), Ws)
    y0 = min(max(0.0, raw[1]), Hs)
    x1, y1 = max(x0, min(Ws, raw[2])), max(y0, min(Hs, raw[3]))
    box = [x0 / Ws * W, y0 / Hs * H, x1 / Ws * W, y1 / Hs * H]
    if unit.get("panel") == "band":
        for axis, (a0, a1, side, size) in enumerate(((x0, x1, Ws, W), (y0, y1, Hs, H))):
            if a1 - a0 >= BAND_SPAN * side:
                continue
            # Thickness keeps the band's own size, even where it bled off canvas.
            thick = min((raw[axis + 2] - raw[axis]) * s, size)
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


def _bleeds(src: dict, unit: dict) -> tuple[bool, bool, bool, bool]:
    """Which source canvas edges (left, top, right, bottom) the unit crosses."""
    x0, y0, x1, y1 = unit["bbox"]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    return x0 < -0.5, y0 < -0.5, x1 > Ws + 0.5, y1 > Hs + 0.5


def _decor_box(src: dict, unit: dict, s: float, W: float, H: float):
    """(scale, x, y) for a free decoration: relative anchor, flush to the edges it bled over.

    The output must stay on canvas, so a decoration that bled off an edge
    or corner sits flush in that edge or corner instead, scaled by the share
    of it that was visible (sqrt, at least BLEED_KEEP) so it keeps about its
    painted weight rather than growing into a whole floating disc.
    """
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    x0, y0, x1, y1 = unit["bbox"]
    left, top, right, bottom = _bleeds(src, unit)
    if left or top or right or bottom:
        visible = coverage(unit["bbox"], src["canvas"]) * Ws * Hs / max(_area(unit["bbox"]), 1e-9)
        s *= max(BLEED_KEEP, min(1.0, visible ** 0.5))
    bw, bh = (x1 - x0) * s, (y1 - y0) * s
    fit = min(1.0, W / bw if bw else 1.0, H / bh if bh else 1.0)
    s, bw, bh = s * fit, bw * fit, bh * fit
    cx, cy = (x0 + x1) / 2 / Ws * W, (y0 + y1) / 2 / Hs * H
    tx = min(max(cx - bw / 2, 0), W - bw)
    ty = min(max(cy - bh / 2, 0), H - bh)
    if left != right:
        tx = 0.0 if left else W - bw
    if top != bottom:
        ty = 0.0 if top else H - bh
    return s, tx, ty


BLEED_KEEP = 0.6  # least size kept by a bleeding decoration brought fully on canvas
YIELD_STEPS = (0.85, 0.7, 0.55, 0.4)  # sizes an opaque decoration tries before it covers copy


def place_decor(out: dict, src: dict, unit: dict, s: float) -> None:
    """Keep the decoration's relative anchor on the canvas, scaled by `s`, flush to edges it bled over."""
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    s, tx, ty = _decor_box(src, unit, s, W, H)
    place_rigid(out, src, unit, s, tx, ty)


def place_follower(out: dict, src: dict, unit: dict, leader: dict, shrink: float | None = None) -> float:
    """Move a decoration with the content unit it surrounds (already placed in `out`).

    It keeps its centre offset from the leader, scaled like the leader. When
    the result would leave the canvas it shrinks about that centre (rings
    stay concentric); `shrink` imposes a factor shared by all followers of
    one leader. Returns the factor it needed on its own.
    """
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    lx0, ly0, lx1, ly1 = leader.get("core_bbox", leader["bbox"])
    nx0, ny0, nx1, ny1 = union(extent(out["elements"][i]) for i in leader.get("core_idx", leader["idx"]))
    s = min((nx1 - nx0) / max(lx1 - lx0, 1e-9), (ny1 - ny0) / max(ly1 - ly0, 1e-9))
    x0, y0, x1, y1 = unit["bbox"]
    bw, bh = (x1 - x0) * s, (y1 - y0) * s
    cx = (nx0 + nx1) / 2 + ((x0 + x1) / 2 - (lx0 + lx1) / 2) * s
    cy = (ny0 + ny1) / 2 + ((y0 + y1) / 2 - (ly0 + ly1) / 2) * s
    need = min(1.0, *(2 * max(room, 0.0) / size for room, size in
                      ((cx, bw), (W - cx, bw), (cy, bh), (H - cy, bh)) if size > 1e-9))
    f = max(FOLLOW_MIN, need if shrink is None else min(shrink, need))
    # The floor must never push the follower past the canvas itself.
    f = min(f, W / bw if bw > 1e-9 else f, H / bh if bh > 1e-9 else f)
    s, bw, bh = s * f, bw * f, bh * f
    tx = min(max(cx - bw / 2, 0), W - bw)
    ty = min(max(cy - bh / 2, 0), H - bh)
    place_rigid(out, src, unit, s, tx, ty)
    return need


FOLLOW_MIN = 0.3  # a follower never shrinks below this share of its leader-relative size


def place_bridge(out: dict, src: dict, unit: dict, units: list[dict]) -> None:
    """Put a bridge back at its relative spot between its two hosts, scaled like them."""
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    centres, scales = [], []
    for j in unit["hosts"]:
        h = units[j]
        sx0, sy0, sx1, sy1 = h.get("core_bbox", h["bbox"])
        x0, y0, x1, y1 = union(extent(out["elements"][i]) for i in h.get("core_idx", h["idx"]))
        centres.append(((x0 + x1) / 2, (y0 + y1) / 2))
        scales.append(math.sqrt(max(1e-9, (x1 - x0) * (y1 - y0)) / max(1e-9, (sx1 - sx0) * (sy1 - sy0))))
    t = unit["between"]
    cx = centres[0][0] + t * (centres[1][0] - centres[0][0])
    cy = centres[0][1] + t * (centres[1][1] - centres[0][1])
    s = sum(scales) / len(scales)
    x0, y0, x1, y1 = unit["bbox"]
    bw, bh = (x1 - x0) * s, (y1 - y0) * s
    fit = min(1.0, W / bw if bw else 1.0, H / bh if bh else 1.0)
    s, bw, bh = s * fit, bw * fit, bh * fit
    place_rigid(out, src, unit, s, min(max(cx - bw / 2, 0), W - bw), min(max(cy - bh / 2, 0), H - bh))


def place_extras(out: dict, src: dict, units: list[dict], s: float) -> None:
    """Place backdrops, panels, bridges and decorations once content is in `out`.

    Followers of one leader share one shrink factor so rings stay
    proportionate; opaque free decorations painted above copy yield
    (shrink toward their anchor) rather than cover it.
    """
    followers = {}
    for u in units:
        if u["kind"] == "bg":
            place_bg(out, u)
        elif u["kind"] == "panel":
            place_panel(out, src, u)
        elif u["kind"] == "bridge":
            place_bridge(out, src, u, units)
        elif u["kind"] == "decor":
            leader = units[u["follow"]] if "follow" in u else None
            if leader is not None and leader["kind"] in ("text", "rigid"):
                followers.setdefault(u["follow"], []).append(u)
            else:
                place_decor(out, src, u, s)
                _yield_to_copy(out, src, units, u)
                _clear_slivers(out, src, units, u)
    for j, group in followers.items():
        shared = min(place_follower(out, src, u, units[j]) for u in group)
        if len(group) > 1:
            for u in group:
                place_follower(out, src, u, units[j], shared)


def _covers(out, src, unit, units) -> float:
    """Share of copy and art painted below `unit` that its (opaque) fill now hides, beyond the source."""
    els = src["elements"]
    order = _order(src)
    z = min(order[i] for i in unit["idx"])
    hidden = 0.0
    for v in units:
        if v["kind"] not in ("text", "rigid"):
            continue
        for i in v["idx"]:
            if order[i] >= z:
                continue
            before = _point_share(ink_box(els[i]), [els[k] for k in unit["idx"]])
            after = _point_share(ink_box(out["elements"][i]), [out["elements"][k] for k in unit["idx"]])
            hidden += max(0.0, after - before)
    return hidden


def _point_share(box, shapes) -> float:
    """Share of a 5x5 grid of points in `box` inside any of `shapes` (rectangles or ellipses, unrotated)."""
    x0, y0, x1, y1 = box
    hits = 0
    for a in range(5):
        for b in range(5):
            px, py = x0 + (a + 0.5) * (x1 - x0) / 5, y0 + (b + 0.5) * (y1 - y0) / 5
            for m in shapes:
                w, h = m["width"], m["height"]
                if w <= 0 or h <= 0 or not (m["x"] <= px <= m["x"] + w and m["y"] <= py <= m["y"] + h):
                    continue
                if (m.get("shape_type") == "ellipse"
                        and ((px - m["x"] - w / 2) / (w / 2)) ** 2 + ((py - m["y"] - h / 2) / (h / 2)) ** 2 > 1):
                    continue
                hits += 1
                break
    return hits / 25


def _yield_to_copy(out, src, units, u):
    """An opaque free decoration painted above content shrinks toward its anchor until it stops hiding it."""
    els = src["elements"]
    if any(els[i]["type"] != "shape" or els[i].get("rotation", 0) or fill_alpha(els[i]) * els[i].get("opacity", 1) < 0.5
           for i in u["idx"]):
        return
    if _covers(out, src, u, units) <= 0.04:
        return
    left, top, right, bottom = _bleeds(src, u)
    base = union(extent(out["elements"][i]) for i in u["idx"])
    best = None
    for step in YIELD_STEPS:
        bw, bh = (base[2] - base[0]) * step, (base[3] - base[1]) * step
        # Shrink toward the edges it is anchored on (its centre otherwise).
        tx = base[0] if left and not right else base[2] - bw if right and not left else (base[0] + base[2] - bw) / 2
        ty = base[1] if top and not bottom else base[3] - bh if bottom and not top else (base[1] + base[3] - bh) / 2
        scale = bw / max(u["bbox"][2] - u["bbox"][0], 1e-9)
        place_rigid(out, src, u, scale, tx, ty)
        covered = _covers(out, src, u, units)
        if best is None or covered < best[0] - 1e-9:
            best = (covered, scale, tx, ty)
        if covered <= 0.04:
            return
    place_rigid(out, src, u, best[1], best[2], best[3])


SLIVER = (0.5, 0.98)  # hidden share of a decoration that would leave only slivers visible


def _opaque_boxes(out, src, units, z):
    """Painted boxes of opaque shape content above paint order `z`."""
    boxes = []
    for v in units:
        if v["kind"] not in ("text", "rigid"):
            continue
        for i in v["idx"]:
            m = src["elements"][i]
            if (m["type"] == "shape" and fill_alpha(m) >= 1 and m.get("opacity", 1) >= 1
                    and m.get("z_index", i) > z):
                boxes.append(aabb(out["elements"][i]))
    return boxes


def _hidden(box, boxes):
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    covered = 0.0
    for b in boxes:
        w = min(box[2], b[2]) - max(box[0], b[0])
        h = min(box[3], b[3]) - max(box[1], b[1])
        if w > 0 and h > 0:
            covered += w * h
    return min(1.0, covered / area)


def _clear_slivers(out, src, units, u):
    """Move a decoration that would peek out from under a button as thin slivers.

    When most but not all of it is hidden under opaque content, it slides by
    the smallest step (staying on canvas) that clears that content, or, if
    no slide works, centres fully under the largest cover it fits under.
    """
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    z = min(src["elements"][i].get("z_index", i) for i in u["idx"])
    boxes = _opaque_boxes(out, src, units, z)
    if not boxes:
        return
    box = union(aabb(out["elements"][i]) for i in u["idx"])
    if not SLIVER[0] < _hidden(box, boxes) < SLIVER[1]:
        return
    bw, bh = box[2] - box[0], box[3] - box[1]
    hit = [b for b in boxes if min(box[2], b[2]) > max(box[0], b[0]) and min(box[3], b[3]) > max(box[1], b[1])]
    x0, y0, x1, y1 = union(hit)
    moves = [(x0 - box[2], 0.0), (x1 - box[0], 0.0), (0.0, y0 - box[3]), (0.0, y1 - box[1])]
    best = None
    for dx, dy in moves:
        moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        if moved[0] < 0 or moved[1] < 0 or moved[2] > W or moved[3] > H or _hidden(moved, boxes) > 0:
            continue
        if best is None or abs(dx) + abs(dy) < abs(best[0]) + abs(best[1]):
            best = (dx, dy)
    if best is None:
        cover = max(hit, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        if bw > cover[2] - cover[0] or bh > cover[3] - cover[1]:
            return
        best = ((cover[0] + cover[2] - bw) / 2 - box[0], (cover[1] + cover[3] - bh) / 2 - box[1])
    for i in u["idx"]:
        out["elements"][i]["x"] += best[0]
        out["elements"][i]["y"] += best[1]
