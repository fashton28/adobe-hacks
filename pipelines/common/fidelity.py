"""Relationship checks between a source design and a resized output.

The AI judges score faithfulness: a resize must not break what the source
design relied on. Three relationships are checked on a small z-aware raster
of both designs, painted in the renderer's order (`z_index`, then array
order) with shape fills, element opacity and the actual asset pixels
(read-only, downsampled):

* occlusion: no text, image or content shape may be covered by later-painted
  elements more than in the source (an opaque hill over the message);
* visibility: text keeps its contrast against what is painted behind it
  (every style-run colour counts), images do not dissolve into a backdrop of
  their own colour, and content shapes (a form field, a button) stay distinct
  from their backdrop;
* containment: an element that sat inside a card, panel or badge shape
  (`CONTAIN` of its painted box) and painted above it stays inside it.

Each failure is one violation; `adaptive.search` ranks candidates by the
violation count right after text overflow, so these are hard constraints
whenever any candidate satisfies them. Everything is geometric: no ids,
names or notes are read.
"""

import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image

from .assets import ASSETS_DIR, asset_info
from .geometry import aabb
from .units import build_units, ink_box

PIXELS = 160 * 160  # raster budget; the scale is uniform so shapes keep their geometry
ASSET_SIDE = 160  # longest side of the cached asset thumbnails
CONTAIN = 0.85  # share of an element's painted box inside its container
OCCLUSION_GROWTH = 0.12  # extra covered share of an image or shape before it counts
TEXT_OCCLUSION_GROWTH = 0.01  # copy is lost far sooner: even a few hidden letters break it
COVER_ALPHA = 0.5  # accumulated alpha above an element that hides a pixel
CONTRAST_MIN = 3.0  # WCAG-like ratio that always counts as readable
CONTRAST_KEEP = 0.75  # below this share of the source contrast, text has lost its backdrop
CAMO_DISTANCE = 0.12  # colour distance (0..1) at which an image pixel blends into its backdrop
CAMO_MAX = 0.45  # share of camouflaged image pixels that counts as dissolved...
CAMO_GROWTH = 0.25  # ...when it also grew this much over the source
SHAPE_KEEP = 0.5  # a content shape keeps at least this share of its source distinctness
SHAPE_VISIBLE = 0.03  # distinctness below which a shape was never meant to stand out
MIN_PIXELS = 4  # raster pixels a shape needs before its distinctness is measured


def parse_rgba(value, default=(0.0, 0.0, 0.0, 1.0)):
    """(r, g, b, a) with channels in 0..1, parsed like the renderer (rgb()/rgba() only)."""
    import re

    match = re.match(r"\s*rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", str(value or ""))
    if not match:
        return default
    r, g, b = (int(float(match.group(i))) / 255.0 for i in (1, 2, 3))
    a = float(match.group(4)) if match.group(4) is not None else 1.0
    return r, g, b, min(max(a, 0.0), 1.0)


def paint_order(design: dict) -> list[int]:
    """Element indices in the renderer's paint order (stable sort on z_index, default 0)."""
    els = design["elements"]
    return sorted(range(len(els)), key=lambda i: (els[i].get("z_index", 0) or 0, i))


@lru_cache(maxsize=32)
def _thumb(asset_id: str):
    """Downsampled RGBA asset pixels (0..1 floats), or None when the file is missing."""
    if not asset_info(asset_id)["available"]:
        return None
    with Image.open(ASSETS_DIR / asset_id) as image:
        image = image.convert("RGBA")
        f = min(1.0, ASSET_SIDE / max(image.width, image.height))
        small = image.resize((max(1, round(image.width * f)), max(1, round(image.height * f))), Image.BILINEAR)
        return np.asarray(small, dtype=np.float32) / 255.0, image.width, image.height


def _luminance(rgb):
    c = np.where(rgb <= 0.03928, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    return (np.maximum(la, lb) + 0.05) / (np.minimum(la, lb) + 0.05)


class _Raster:
    """Painter's-algorithm raster at a reduced, uniform scale."""

    def __init__(self, design: dict):
        W, H = design["canvas"]["width"], design["canvas"]["height"]
        self.f = min(1.0, math.sqrt(PIXELS / max(1.0, W * H)))
        self.gx, self.gy = max(1, round(W * self.f)), max(1, round(H * self.f))
        self.sx, self.sy = W / self.gx, H / self.gy  # canvas px per raster px
        self.rgb = np.ones((self.gy, self.gx, 3), dtype=np.float32)  # renderer canvas is white

    def window(self, box):
        """Raster slice (rows, cols) whose pixel centres lie in the box; never empty for a box on canvas."""
        x0, y0, x1, y1 = box
        c0 = max(0, min(self.gx - 1, math.ceil(x0 / self.sx - 0.5)))
        c1 = max(c0 + 1, min(self.gx, math.ceil(x1 / self.sx - 0.5)))
        r0 = max(0, min(self.gy - 1, math.ceil(y0 / self.sy - 0.5)))
        r1 = max(r0 + 1, min(self.gy, math.ceil(y1 / self.sy - 0.5)))
        return slice(r0, r1), slice(c0, c1)

    def layer(self, el: dict):
        """(window, alpha, rgb) for a shape or image element, or None if it paints nothing."""
        w, h = float(el.get("width", 0)), float(el.get("height", 0))
        if w <= 0 or h <= 0:
            return None
        win = self.window(aabb(el))
        rows, cols = win
        ys = (np.arange(rows.start, rows.stop, dtype=np.float32) + 0.5) * self.sy
        xs = (np.arange(cols.start, cols.stop, dtype=np.float32) + 0.5) * self.sx
        X, Y = np.meshgrid(xs, ys)
        cx, cy = el["x"] + w / 2, el["y"] + h / 2
        r = math.radians(el.get("rotation", 0) or 0)
        # Pixel centre in the element's own (unrotated) frame.
        dx, dy = X - cx, Y - cy
        u = dx * math.cos(r) + dy * math.sin(r) + w / 2
        v = -dx * math.sin(r) + dy * math.cos(r) + h / 2
        inside = (u >= 0) & (u <= w) & (v >= 0) & (v <= h)
        opacity = float(el.get("opacity", 1) if el.get("opacity") is not None else 1)
        if el["type"] == "shape":
            red, green, blue, a = parse_rgba(el.get("fill_color"), (200 / 255, 200 / 255, 200 / 255, 1.0))
            if el.get("shape_type") == "ellipse":
                inside &= ((u - w / 2) / (w / 2)) ** 2 + ((v - h / 2) / (h / 2)) ** 2 <= 1.0
            alpha = inside.astype(np.float32) * a * opacity
            rgb = np.broadcast_to(np.array([red, green, blue], dtype=np.float32), alpha.shape + (3,))
            return win, alpha, rgb
        if el["type"] != "image":
            return None
        thumb = _thumb(str(el.get("asset_id", "")))
        if thumb is None:  # the renderer paints an opaque grey placeholder box
            alpha = inside.astype(np.float32) * opacity
            rgb = np.broadcast_to(np.array([214, 214, 214], dtype=np.float32) / 255, alpha.shape + (3,))
            return win, alpha, rgb
        pixels, iw, ih = thumb
        fit = el.get("fit", "contain")
        if fit in ("contain", "cover"):
            s = min(w / iw, h / ih) if fit == "contain" else max(w / iw, h / ih)
            sx = sy = s
        else:
            sx, sy = w / iw, h / ih
        ox, oy = (w - iw * sx) / 2, (h - ih * sy) / 2
        th, tw = pixels.shape[:2]
        px = ((u - ox) / sx * tw / iw).astype(np.int64)
        py = ((v - oy) / sy * th / ih).astype(np.int64)
        valid = inside & (px >= 0) & (px < tw) & (py >= 0) & (py < th)
        sample = pixels[np.clip(py, 0, th - 1), np.clip(px, 0, tw - 1)]
        alpha = sample[..., 3] * valid * opacity
        return win, alpha.astype(np.float32), sample[..., :3]


def _text_colours(el: dict):
    colours = [parse_rgba(el.get("color"), (0.0, 0.0, 0.0, 1.0))]
    for run in el.get("style_runs") or []:
        if run.get("color"):
            colours.append(parse_rgba(run["color"], colours[0]))
    return colours


def analyse(design: dict, roles: dict) -> dict:
    """Per-element backdrop and coverage measurements.

    `roles` maps element index -> "text" | "image" | "shape" for the elements
    to measure. Returns index -> dict(contrast | camo | distinct, occluded).
    """
    els = design["elements"]
    raster = _Raster(design)
    order = paint_order(design)
    layers = {}
    result = {}
    boxes = {}
    for i in order:
        el = els[i]
        role = roles.get(i)
        if role is not None:
            box = ink_box(el) if el["type"] != "shape" else aabb(el)
            boxes[i] = raster.window(box)
            rows, cols = boxes[i]
            backdrop = raster.rgb[rows, cols].copy()
            entry = {}
            if role == "text":
                worst = math.inf
                for red, green, blue, a in _text_colours(el):
                    colour = np.array([red, green, blue], dtype=np.float32)
                    effective = colour * a + backdrop * (1 - a)
                    worst = min(worst, float(np.median(_contrast(effective, backdrop))))
                entry["contrast"] = worst
            result[i] = entry
            result[i]["_backdrop"] = backdrop
        if el["type"] == "text":
            continue
        layer = raster.layer(el)
        if layer is None:
            continue
        (rows, cols), alpha, rgb = layer
        layers[i] = layer
        under = raster.rgb[rows, cols]
        if role == "image":
            solid = alpha > 0.5
            if solid.any():
                dist = np.linalg.norm(rgb - under, axis=-1) / math.sqrt(3)
                result[i]["camo"] = float((dist[solid] < CAMO_DISTANCE).mean())
            else:
                result[i]["camo"] = 0.0
        a = alpha[..., None]
        painted = rgb * a + under * (1 - a)
        if role == "shape":
            inside = alpha > 0
            dist = np.linalg.norm(painted - under, axis=-1) / math.sqrt(3)
            # Hairlines below the raster resolution cannot be judged here.
            result[i]["distinct"] = float(dist[inside].mean()) if inside.sum() >= MIN_PIXELS else None
        raster.rgb[rows, cols] = painted
    # Coverage by everything painted later (text never hides anything here).
    position = {i: n for n, i in enumerate(order)}
    for i, (rows, cols) in boxes.items():
        clear = np.ones((rows.stop - rows.start, cols.stop - cols.start), dtype=np.float32)
        for j, ((lr, lc), alpha, _) in layers.items():
            if position[j] <= position[i]:
                continue
            r0, r1 = max(rows.start, lr.start), min(rows.stop, lr.stop)
            c0, c1 = max(cols.start, lc.start), min(cols.stop, lc.stop)
            if r0 >= r1 or c0 >= c1:
                continue
            clear[r0 - rows.start:r1 - rows.start, c0 - cols.start:c1 - cols.start] *= (
                1 - alpha[r0 - lr.start:r1 - lr.start, c0 - lc.start:c1 - lc.start])
        result[i]["occluded"] = float((1 - clear >= COVER_ALPHA).mean())
        result[i].pop("_backdrop", None)
    return result


def _roles(source: dict, units: list[dict]) -> dict:
    """Which elements are measured: all text, foreground images and content shapes."""
    els = source["elements"]
    roles = {}
    for u in units:
        if u["kind"] in ("bg", "decor"):
            continue
        for i in u["idx"]:
            el = els[i]
            if el["type"] == "text":
                roles[i] = "text"
            elif el["type"] == "image" and u["kind"] != "panel" and asset_info(str(el.get("asset_id", "")))["available"]:
                # Missing-asset placeholders are deliberately tucked away; not measured.
                roles[i] = "image"
            elif el["type"] == "shape" and u["kind"] == "rigid" and el.get("width", 0) > 0 and el.get("height", 0) > 0:
                roles[i] = "shape"
    return roles


def containers(source: dict, units: list[dict]) -> list[tuple[int, int]]:
    """(container index, content index) pairs: content painted above a card/panel/badge shape it lies in.

    Containers are shapes of content or panel units (not backdrops or loose
    decorations) larger than the content. The content's painted box must lie
    at least CONTAIN inside the container's box.
    """
    els = source["elements"]
    order = {i: n for n, i in enumerate(paint_order(source))}
    shapes = [i for u in units if u["kind"] in ("rigid", "panel") for i in u["idx"]
              if els[i]["type"] == "shape" and els[i].get("shape_type") != "line"
              and els[i]["width"] > 0 and els[i]["height"] > 0]
    pairs = []
    for c in shapes:
        cb = aabb(els[c])
        carea = (cb[2] - cb[0]) * (cb[3] - cb[1])
        for u in units:
            if u["kind"] in ("bg", "decor"):
                continue
            for i in u["idx"]:
                if i == c or order[i] < order[c] or els[i]["width"] <= 0 or els[i]["height"] <= 0:
                    continue
                b = ink_box(els[i])
                area = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
                if area >= carea:
                    continue
                if _share_inside(b, cb) >= CONTAIN:
                    pairs.append((c, i))
    return pairs


def _share_inside(b, outer) -> float:
    area = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    w = min(b[2], outer[2]) - max(b[0], outer[0])
    h = min(b[3], outer[3]) - max(b[1], outer[1])
    return max(0.0, w) * max(0.0, h) / area


STACK_GAP = 0.8  # stacked copy closer than this many font sizes reads as one block (a name over its role)
STACK_OVERLAP = 0.5  # ... when it shares this much of the narrower width
STACK_OVERLAP_OUT = 0.3  # in the output the pair must still share this much width
STACK_GROWTH = 2.5  # and its gap may grow at most this much beyond the type scale
STACK_FONT_GAP = 1.2  # (or up to this many font sizes)
STACK_ALIGN = 0.02  # a shared source edge must stay shared within this share of the width
STACK_ALIGN_PX = 4.0
STACK_SIZE_RATIO = 3.0  # copy more than this many times larger than its neighbour is not one block with it


def _ink(design, i):
    return ink_box(design["elements"][i])


def _union_ink(out, els, idx):
    by_id = {el["id"]: el for el in out["elements"]}
    boxes = [ink_box(by_id[els[i]["id"]]) for i in idx]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def neighbours(source: dict, units: list[dict]) -> list:
    """Tightly stacked copy and accent rules: (upper idx, lower idx, gap, reference text index, shared edge).

    Two ungrouped text units, or a text and a divider rule, stacked closer
    than STACK_GAP of the smaller font size and sharing most of their width
    are one block to the reader (a name over its role, an accent rule over a
    tagline). The shared edge (left, centre or right, within STACK_ALIGN of
    the width) must survive too.
    """
    els = source["elements"]
    W = source["canvas"]["width"]

    def rule(u):
        if u["kind"] != "rigid" or len(u["idx"]) != 1 or els[u["idx"][0]]["type"] != "shape":
            return False
        x0, y0, x1, y1 = u["bbox"]
        return min(x1 - x0, y1 - y0) <= 0.1 * max(x1 - x0, y1 - y0) and y1 - y0 < x1 - x0

    items = [u for u in units if u["kind"] == "text" or rule(u)]
    found = []
    for a in items:
        for b in items:
            if a is b or (a["kind"] != "text" and b["kind"] != "text"):
                continue
            ia, ib = a["ink"], b["ink"]
            texts = [els[u["idx"][0]] for u in (a, b) if u["kind"] == "text"]
            ref = min(texts, key=lambda e: e["font_size"])
            if max(e["font_size"] for e in texts) > STACK_SIZE_RATIO * ref["font_size"]:
                continue  # a display glyph over body copy is decoration, not one block
            gap = ib[1] - ia[3]
            narrow = min(ia[2] - ia[0], ib[2] - ib[0])
            overlap = min(ia[2], ib[2]) - max(ia[0], ib[0])
            if not (-0.25 * ref["font_size"] <= gap <= STACK_GAP * ref["font_size"]) or overlap < STACK_OVERLAP * narrow:
                continue
            if (ia[1] + ia[3]) >= (ib[1] + ib[3]):
                continue
            tol = STACK_ALIGN * W
            edge = next((name for name, d in (("left", abs(ia[0] - ib[0])),
                                              ("centre", abs((ia[0] + ia[2]) / 2 - (ib[0] + ib[2]) / 2)),
                                              ("right", abs(ia[2] - ib[2]))) if d <= tol), None)
            found.append((a["idx"], b["idx"], gap, els.index(ref), edge))
    return found


SOFT = {"separated"}  # relationships traded against legibility in the score rather than vetoed


_SOURCE_CACHE: list = []  # [(fingerprint, analysis)]


def _source_facts(source: dict):
    key = json.dumps(source, sort_keys=True, default=str)
    if not _SOURCE_CACHE or _SOURCE_CACHE[0][0] != key:
        units = build_units(source)
        roles = _roles(source, units)
        unit_of = {i: n for n, u in enumerate(units) for i in u["idx"]}
        _SOURCE_CACHE[:] = [(key, (roles, analyse(source, roles), containers(source, units), unit_of,
                                   neighbours(source, units)))]
    return _SOURCE_CACHE[0][1]


def check(source: dict, out: dict) -> dict:
    """Fidelity violations of `out` against `source` (see module docstring).

    `violations` counts distinct (kind, source unit) failures, so a dashed
    border of fifty dashes leaving its card is one failure, not fifty.
    """
    roles, before, pairs, unit_of, stacks = _source_facts(source)
    after = analyse(out, roles)
    els, by_id = source["elements"], {el["id"]: el for el in out["elements"]}
    details = []
    for i, role in roles.items():
        a, b = after.get(i, {}), before.get(i, {})
        name = els[i]["id"]
        allowed = TEXT_OCCLUSION_GROWTH if role == "text" else OCCLUSION_GROWTH
        if a.get("occluded", 0) > b.get("occluded", 0) + allowed:
            details.append(("occluded", name, round(b.get("occluded", 0), 2), round(a["occluded"], 2)))
        if role == "text" and a.get("contrast", 99) < min(CONTRAST_MIN, CONTRAST_KEEP * b.get("contrast", 99)):
            details.append(("contrast", name, round(b.get("contrast", 0), 2), round(a["contrast"], 2)))
        if role == "image" and a.get("camo", 0) > max(CAMO_MAX, b.get("camo", 0) + CAMO_GROWTH):
            details.append(("camouflaged", name, round(b.get("camo", 0), 2), round(a["camo"], 2)))
        if (role == "shape" and a.get("distinct") is not None and (b.get("distinct") or 0) >= SHAPE_VISIBLE
                and a["distinct"] < SHAPE_KEEP * b["distinct"]):
            details.append(("indistinct", name, round(b["distinct"], 3), round(a.get("distinct", 0), 3)))
    for c, i in pairs:
        share = _share_inside(ink_box(by_id[els[i]["id"]]), aabb(by_id[els[c]["id"]]))
        if share < CONTAIN - 0.05:
            details.append(("escaped", els[i]["id"], els[c]["id"], round(share, 2)))
    W = out["canvas"]["width"]
    for upper, lower, gap, ref, edge in stacks:
        a = _union_ink(out, els, upper)
        b = _union_ink(out, els, lower)
        size = by_id[els[ref]["id"]]["font_size"]
        k = size / els[ref]["font_size"]
        narrow = min(a[2] - a[0], b[2] - b[0])
        overlap = min(a[2], b[2]) - max(a[0], b[0])
        out_gap = b[1] - a[3]
        tol = max(STACK_ALIGN_PX, STACK_ALIGN * W)
        aligned = {"left": abs(a[0] - b[0]), "centre": abs((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2),
                   "right": abs(a[2] - b[2])}.get(edge, 0.0) <= tol
        if (out_gap < -STACK_ALIGN_PX or overlap < STACK_OVERLAP_OUT * max(narrow, 1e-9) or not aligned
                or out_gap > max(STACK_GROWTH * max(gap, 0.0) * k, STACK_FONT_GAP * size)):
            details.append(("separated", els[lower[0]]["id"], els[upper[0]]["id"], round(out_gap, 1)))
    ids = {el["id"]: i for i, el in enumerate(els)}
    distinct = {(d[0], unit_of.get(ids[d[1]])) for d in details}
    soft = sum(kind in SOFT for kind, _ in distinct)
    return {"violations": len(distinct) - soft, "soft": soft, "details": details}
