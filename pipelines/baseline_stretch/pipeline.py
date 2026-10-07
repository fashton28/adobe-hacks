"""The original starter baseline: independent x/y stretch. Kept for benchmarking only."""

from typing import Any


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    scale_x = target_canvas["width"] / source["canvas"]["width"]
    scale_y = target_canvas["height"] / source["canvas"]["height"]

    out_elements = []
    for el in source["elements"]:
        el = dict(el)
        el["x"] = el["x"] * scale_x
        el["y"] = el["y"] * scale_y
        el["width"] = el["width"] * scale_x
        el["height"] = el["height"] * scale_y
        if el["type"] == "text":
            el["font_size"] = max(1.0, el["font_size"] * min(scale_x, scale_y))
        out_elements.append(el)

    return {
        "canvas": {"width": target_canvas["width"], "height": target_canvas["height"]},
        "elements": out_elements,
    }
