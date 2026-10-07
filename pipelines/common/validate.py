"""Structural checks on a resized design (local proxy, not the official scorer)."""

import math
from collections import Counter

from .geometry import aabb

EPS = 0.5
RATIO_TOL = 0.05


def is_background(el: dict, canvas: dict) -> bool:
    if el.get("type") != "image":
        return False
    x0, y0, x1, y1 = aabb(el)
    cover = max(0, min(x1, canvas["width"]) - max(x0, 0)) * max(0, min(y1, canvas["height"]) - max(y0, 0))
    frac = cover / (canvas["width"] * canvas["height"])
    return frac >= 0.85 or (el.get("fit") == "cover" and frac >= 0.5)


def validate(source: dict, target: dict, out: dict) -> list[str]:
    problems = []
    if out.get("canvas") != {"width": target["width"], "height": target["height"]}:
        problems.append("canvas does not match target")
    if Counter(e["id"] for e in source["elements"]) != Counter(e.get("id") for e in out["elements"]):
        problems.append("element ids differ from source")
        return problems
    src = {e["id"]: e for e in source["elements"]}
    W, H = target["width"], target["height"]
    for el in out["elements"]:
        s = src[el["id"]]
        nums = [el["x"], el["y"], el["width"], el["height"]] + ([el["font_size"]] if el["type"] == "text" else [])
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in nums):
            problems.append(f"{el['id']}: non-finite value")
            continue
        if el["width"] < 0 or el["height"] < 0 or (el["type"] == "text" and el["font_size"] < 1):
            problems.append(f"{el['id']}: negative size / font < 1")
        x0, y0, x1, y1 = aabb(el)
        if x0 < -EPS or y0 < -EPS or x1 > W + EPS or y1 > H + EPS:
            problems.append(f"{el['id']}: off-canvas")
        if el["type"] == "image" and not is_background(s, source["canvas"]) and s["height"] and s["width"] and el["height"]:
            if abs((el["width"] / el["height"]) / (s["width"] / s["height"]) - 1) > RATIO_TOL:
                problems.append(f"{el['id']}: image aspect ratio changed")
        if el["type"] == "text" and (el.get("content") != s.get("content") or el.get("font_family") != s.get("font_family")):
            problems.append(f"{el['id']}: content/font_family changed")
    return problems
