"""Structural checks on a resized design (local proxy, not the official scorer)."""

import math
from collections import Counter

from .geometry import aabb, extent

EPS = 0.5
RATIO_TOL = 0.05
BAND_SPAN = 0.9  # edge bands span this fraction of one canvas side
EDGE = 0.02  # "touches the edge" tolerance, as a fraction of that side


def edge_band(el: dict, canvas: dict) -> bool:
    """An unrotated rectangle or line spanning one side of the canvas along an edge.

    Such a band frames the canvas (a footer strip, a side scrim); it stretches
    with the canvas even inside an explicit group, whose other members keep
    one shared transform.
    """
    if el.get("type") != "shape" or el.get("rotation", 0) or el.get("shape_type") not in ("rectangle", "line"):
        return False
    x0, y0, x1, y1 = aabb(el)
    W, H = canvas["width"], canvas["height"]
    wide = min(x1, W) - max(x0, 0) >= BAND_SPAN * W
    tall = min(y1, H) - max(y0, 0) >= BAND_SPAN * H
    return ((wide and (y0 <= EDGE * H or y1 >= (1 - EDGE) * H))
            or (tall and (x0 <= EDGE * W or x1 >= (1 - EDGE) * W)))


def validate_input(source: dict, target: dict) -> None:
    """Reject ambiguous identities and unusable geometry before searching."""
    for name, canvas in (("source", source.get("canvas", {})), ("target", target)):
        if any(type(canvas.get(k)) is not int or canvas[k] < 1 for k in ("width", "height")):
            raise ValueError(f"{name} canvas must have positive integer dimensions")
    elements = source.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("source must contain at least one element")
    ids = [e.get("id") for e in elements if isinstance(e, dict)]
    if len(ids) != len(elements) or any(not isinstance(i, str) for i in ids):
        raise ValueError("source elements must have string ids")
    if len(set(ids)) != len(ids):
        raise ValueError("source element ids must be unique")
    for el in elements:
        keys = ("x", "y", "width", "height", "rotation", "letter_spacing", "stroke_width", "corner_radius")
        if el.get("type") == "text":
            keys += ("font_size", "line_height")
        for key in keys:
            value = el.get(key, {"rotation": 0, "letter_spacing": 0,
                                 "stroke_width": 0, "corner_radius": 0, "line_height": 1.2}.get(key))
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{el['id']}: {key} must be finite")
        if el["width"] < 0 or el["height"] < 0:
            raise ValueError(f"{el['id']}: negative dimensions")
        if el.get("type") == "text" and el["font_size"] < 1:
            raise ValueError(f"{el['id']}: invalid typography")


def is_background(el: dict, canvas: dict) -> bool:
    # Only existing cover images may crop. A large contain/fill foreground
    # must not gain an aspect-ratio exemption just because it covers the canvas.
    if el.get("type") != "image" or el.get("fit", "contain") != "cover" or el.get("rotation", 0):
        return False
    x0, y0, x1, y1 = aabb(el)
    cover = max(0, min(x1, canvas["width"]) - max(x0, 0)) * max(0, min(y1, canvas["height"]) - max(y0, 0))
    frac = cover / (canvas["width"] * canvas["height"])
    return frac >= 0.85


def validate(source: dict, target: dict, out: dict) -> list[str]:
    problems = []
    if not isinstance(out, dict) or not isinstance(out.get("elements"), list):
        return ["output is missing an elements list"]
    if out.get("canvas") != {"width": target["width"], "height": target["height"]}:
        problems.append("canvas does not match target")
    if any(not isinstance(e, dict) or not isinstance(e.get("id"), str) for e in out["elements"]):
        return problems + ["elements must be objects with string ids"]
    if len({e["id"] for e in source["elements"]}) != len(source["elements"]):
        return problems + ["source element ids are not unique"]
    if set(out) != {"canvas", "elements"}:
        problems.append("unexpected top-level fields")
    if Counter(e["id"] for e in source["elements"]) != Counter(e.get("id") for e in out["elements"]):
        problems.append("element ids differ from source")
        return problems
    src = {e["id"]: e for e in source["elements"]}
    W, H = target["width"], target["height"]
    for el in out["elements"]:
        s = src[el["id"]]
        required = ["type", "x", "y", "width", "height"] + {
            "text": ["content", "font_family", "font_size", "color"],
            "image": ["asset_id"], "shape": ["shape_type", "fill_color"],
        }.get(s["type"], [])
        missing = [key for key in required if key not in el]
        if missing:
            problems.append(f"{el['id']}: missing {', '.join(missing)}")
            continue
        mutable = {"x", "y", "width", "height"} | {
            "text": {"font_size", "letter_spacing"}, "shape": {"corner_radius", "stroke_width"},
        }.get(s["type"], set())
        for key in (s.keys() | el.keys()) - mutable:
            if (key in el) != (key in s) or el.get(key) != s.get(key):
                problems.append(f"{el['id']}: {key} changed")
        nums = [el["x"], el["y"], el["width"], el["height"], el.get("rotation", 0)]
        nums += [el[key] for key in ("font_size", "letter_spacing", "line_height", "corner_radius", "stroke_width", "opacity") if key in el]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in nums):
            problems.append(f"{el['id']}: non-finite value")
            continue
        if el["width"] < 0 or el["height"] < 0 or (el["type"] == "text" and el["font_size"] < 1):
            problems.append(f"{el['id']}: negative size / font < 1")
        if any(s[key] > 0 and el[key] == 0 for key in ("width", "height")):
            problems.append(f"{el['id']}: visible element collapsed")
        # Both the rotated bounds and the unrotated x/y/width/height box.
        x0, y0, x1, y1 = extent(el)
        if x0 < -EPS or y0 < -EPS or x1 > W + EPS or y1 > H + EPS:
            problems.append(f"{el['id']}: off-canvas")
        if (el["type"] == "image" and not is_background(s, source["canvas"]) and s["height"] and s["width"]
                and el["height"] and abs((el["width"] / el["height"]) / (s["width"] / s["height"]) - 1) > RATIO_TOL):
            problems.append(f"{el['id']}: image aspect ratio changed")
        if el["type"] == "text" and (el.get("content") != s.get("content") or el.get("font_family") != s.get("font_family")):
            problems.append(f"{el['id']}: content/font_family changed")
    # Explicit groups must share one geometry transform. Font fitting is
    # permitted independently; moving a label away from its button is not.
    groups = {}
    by_id = {e["id"]: e for e in out["elements"]}
    for s in source["elements"]:
        if s.get("group_id"):
            groups.setdefault(s["group_id"], []).append(s)
    # An edge band inside a group stretches with the canvas; the rest of
    # the group keeps one transform.
    for gid, members in groups.items():
        if len(members) > 1:
            groups[gid] = [s for s in members if not edge_band(s, source["canvas"])]
    for gid, members in groups.items():
        if len(members) < 2:
            continue
        anchor = next((s for s in members if s["width"] > 0 or s["height"] > 0), None)
        if anchor is None:
            continue
        a = by_id[anchor["id"]]
        if any(not all(type(e.get(k)) in (int, float) and math.isfinite(e[k])
                       for k in ("x", "y", "width", "height")) for e in (by_id[s["id"]] for s in members)):
            continue  # Missing/nonfinite fields have already been reported.
        key = "width" if anchor["width"] > 0 else "height"
        scale = a[key] / anchor[key]
        dx, dy = a["x"] - anchor["x"] * scale, a["y"] - anchor["y"] * scale
        if any(abs(by_id[s["id"]][k] - (s[k] * scale + offset)) > EPS
               for s in members for k, offset in (("x", dx), ("y", dy), ("width", 0), ("height", 0))):
            problems.append(f"group {gid}: inconsistent geometry transform")
    return problems
