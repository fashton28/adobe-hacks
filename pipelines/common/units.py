"""Grouping of source elements into layout units, and helpers to place them.

Unit kinds:
  bg     full-bleed background image  -> stretched/cropped to the target
  decor  ungrouped translucent / bleeding shape -> anchored to its relative spot
  text   ungrouped text element       -> re-fitted (font size + wrapping)
  rigid  images and explicit groups   -> uniformly scaled + translated as one piece
"""

import copy

from .geometry import aabb, union
from .validate import is_background


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
        if len(members) == 1:
            m = members[0]
            x0, y0, x1, y1 = u["bbox"]
            bleeds = x0 < 0 or y0 < 0 or x1 > canvas["width"] or y1 > canvas["height"]
            if is_background(m, canvas):
                u["kind"] = "bg"
            elif m["type"] == "text":
                u["kind"] = "text"
            elif m["type"] == "shape" and (m.get("opacity", 1) < 1 or bleeds):
                u["kind"] = "decor"
            else:
                u["kind"] = "rigid"
        else:
            u["kind"] = "rigid"
        u["images_only"] = u["kind"] == "rigid" and all(m["type"] == "image" for m in members)
    return units


def copy_design(source: dict, target: dict) -> dict:
    return {
        "canvas": {"width": target["width"], "height": target["height"]},
        "elements": copy.deepcopy(source["elements"]),
    }


def place_rigid(out: dict, src: dict, unit: dict, s: float, tx: float, ty: float) -> None:
    """Scale the unit by `s` about its bbox top-left and move that corner to (tx, ty)."""
    x0, y0, _, _ = unit["bbox"]
    for i in unit["idx"]:
        m, o = src["elements"][i], out["elements"][i]
        cx = tx + (m["x"] + m["width"] / 2 - x0) * s
        cy = ty + (m["y"] + m["height"] / 2 - y0) * s
        o["width"], o["height"] = m["width"] * s, m["height"] * s
        o["x"], o["y"] = cx - o["width"] / 2, cy - o["height"] / 2
        if m["type"] == "text":
            o["font_size"] = max(1.0, m["font_size"] * s)
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
