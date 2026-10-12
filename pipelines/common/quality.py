"""Independent, inspectable quality proxies; these are not official scores."""

import math
import statistics

from .geometry import aabb, overlap_area, union
from .assets import asset_info, unavailable_unit
from .text import measure, text_height
from .units import build_units
from .validate import is_background


def metrics(source: dict, out: dict) -> dict:
    src_by_id = {el["id"]: el for el in source["elements"]}
    images = []
    for el in out["elements"]:
        if el["type"] != "image" or is_background(src_by_id[el["id"]], source["canvas"]):
            continue
        info = asset_info(el["asset_id"])
        visible_w, visible_h = 0, 0
        if info["available"] and info["visible_bounds"]:
            x0, y0, x1, y1 = info["visible_bounds"]
            sx, sy = el["width"] / info["width"], el["height"] / info["height"]
            fit = el.get("fit", "contain")
            if fit in ("contain", "cover"):
                sx = sy = min(sx, sy) if fit == "contain" else max(sx, sy)
            dx, dy = (el["width"] - info["width"] * sx) / 2, (el["height"] - info["height"] * sy) / 2
            visible_w = max(0, min(el["width"], dx + x1 * sx) - max(0, dx + x0 * sx))
            visible_h = max(0, min(el["height"], dy + y1 * sy) - max(0, dy + y0 * sy))
        images.append({"id": el["id"], "asset_id": el["asset_id"], "available": info["available"],
                       "visible_width": visible_w, "visible_height": visible_h})
    texts = []
    for el in out["elements"]:
        if el["type"] != "text":
            continue
        lines, widest = measure(el, el["font_size"], el["width"])
        height = text_height(el, el["font_size"], lines)
        texts.append({"id": el["id"], "font_size": el["font_size"], "lines": lines,
                      "width_overflow": max(0, widest - el["width"]),
                      "height_overflow": max(0, height - el["height"])})
    sizes = [t["font_size"] for t in texts]
    by_id = {el["id"]: el for el in out["elements"]}
    boxes = [(u, union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"]))
             for u in build_units(source) if u["kind"] not in ("bg", "decor") and not unavailable_unit(source, u)]
    shifts = []
    for u, box in boxes:
        original = u["bbox"]
        shifts.append(math.hypot(
            (box[0] + box[2]) / (2 * out["canvas"]["width"]) - (original[0] + original[2]) / (2 * source["canvas"]["width"]),
            (box[1] + box[3]) / (2 * out["canvas"]["height"]) - (original[1] + original[3]) / (2 * source["canvas"]["height"])))
    overlaps = []
    for i, (u, a) in enumerate(boxes):
        for v, b in boxes[i + 1:]:
            area = overlap_area(a, b)
            if area > 0.5:
                denom = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                overlaps.append({"a": [source["elements"][j]["id"] for j in u["idx"]],
                                 "b": [source["elements"][j]["id"] for j in v["idx"]],
                                 "fraction": area / max(denom, 1e-9)})
    return {"min_font": min(sizes, default=0), "median_font": statistics.median(sizes) if sizes else 0,
            "below_6px": sum(s < 6 for s in sizes), "below_10px": sum(s < 10 for s in sizes),
            "text_overflows": sum(t["width_overflow"] > 0.5 or t["height_overflow"] > 0.5 for t in texts),
            "overlap_pairs": len(overlaps), "overlap_severity": sum(p["fraction"] for p in overlaps),
            "layout_shift": sum(shifts) / len(shifts) if shifts else 0,
            "texts": texts, "overlaps": overlaps, "images": images,
            "missing_assets": [im["asset_id"] for im in images if not im["available"]]}


def score(source: dict, out: dict) -> float:
    q = metrics(source, out)
    sizes = [max(1, t["font_size"]) for t in q["texts"]]
    # Absolute legibility matters: preserving a tiny source font ratio should
    # not beat readable supporting copy merely because a headline grew more.
    readability = (0.6 * math.log(min(sizes) / 12)
                   + 0.4 * sum(math.log(min(s, 48) / 12) for s in sizes) / len(sizes)) if sizes else 0
    src = {el["id"]: el for el in source["elements"]}
    images = [math.log(max(0.001, min(1.5, el["width"] / src[el["id"]]["width"])))
              for el in out["elements"] if el["type"] == "image" and src[el["id"]]["width"] > 0
              and not is_background(src[el["id"]], source["canvas"])
              and asset_info(el["asset_id"])["available"]]
    return (readability + (0.25 * sum(images) / len(images) if images else 0)
            - 4 * q["text_overflows"] - 2 * q["overlap_severity"])
