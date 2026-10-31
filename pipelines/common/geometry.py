"""Small geometry helpers shared by pipelines."""

import math


def rot_extent(w: float, h: float, deg: float) -> tuple[float, float]:
    """Axis-aligned extent of a w x h box rotated by `deg` about its center."""
    r = math.radians(deg or 0.0)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    return w * c + h * s, w * s + h * c


def aabb(el: dict) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of an element including its rotation."""
    w, h = el["width"], el["height"]
    cx, cy = el["x"] + w / 2, el["y"] + h / 2
    aw, ah = rot_extent(w, h, el.get("rotation", 0.0))
    return cx - aw / 2, cy - ah / 2, cx + aw / 2, cy + ah / 2


def box(el: dict) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the element's unrotated x/y/width/height box."""
    return el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"]


def extent(el: dict) -> tuple[float, float, float, float]:
    """Everything a checker may test for being on-canvas: rotated bounds and the unrotated box.

    Some structural checkers (the starter `self_check`) test the unrotated
    x/y/width/height box, others the painted, rotated bounds. Keeping this
    union on canvas satisfies both definitions.
    """
    a, b = aabb(el), box(el)
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def union(rects) -> tuple[float, float, float, float]:
    rects = list(rects)
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0
