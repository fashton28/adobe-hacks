"""Independent, inspectable quality proxies; these are not official scores."""

import json
import math
import statistics

from .assets import asset_info, unavailable_unit
from .geometry import aabb, overlap_area, union
from .policy import anchor_weight, art_band, spacing
from .text import measure, text_height
from .units import BACKDROP_COVER, build_units, coverage, fill_alpha, ink_box
from .validate import is_background

GRID = 48  # sample points per side for canvas-emptiness estimates
BACKDROP_SLACK = 0.05  # allowed backdrop coverage shortfall before it is a failure
EMPTY_GROWTH = 0.4  # allowed growth of empty canvas share over the source


_UNITS_CACHE: list = []  # [(fingerprint, units)]: one entry, read-only use


def _fingerprint(source: dict) -> str:
    return json.dumps(source, sort_keys=True, default=str)


def _units(source: dict) -> list[dict]:
    """build_units for scoring, memoised for the source being searched (never mutated here)."""
    key = _fingerprint(source)
    if not _UNITS_CACHE or _UNITS_CACHE[0][0] != key:
        _UNITS_CACHE[:] = [(key, build_units(source))]
    return _UNITS_CACHE[0][1]


def _backdrops(source: dict) -> list[dict]:
    """Unrotated elements covering most of the source canvas, whatever the engine thinks they are."""
    return [el for el in source["elements"]
            if not el.get("rotation", 0) and coverage(aabb(el), source["canvas"]) >= BACKDROP_COVER]


def _expected_cover(el: dict, canvas: dict) -> float:
    """Coverage a backdrop can reach: shapes stretch, cover images crop, others keep their ratio."""
    if el["type"] == "shape" or (el["type"] == "image" and el.get("fit", "contain") == "cover"):
        return 1.0
    ratio = el["width"] / max(el["height"], 1e-9)
    target = canvas["width"] / canvas["height"]
    return min(target / ratio, ratio / target)


def _empty_fraction(design: dict) -> float:
    """Share of the canvas where no element paints (painted bounds, grid sampled)."""
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    grid = [bytearray(GRID) for _ in range(GRID)]
    for el in design["elements"]:
        if el["width"] <= 0 or el["height"] <= 0:
            continue
        x0, y0, x1, y1 = ink_box(el)
        # Cells whose centre lies inside the box: centre (i + 0.5) * size / GRID.
        c0, c1 = max(0, math.ceil(x0 * GRID / W - 0.5)), min(GRID, math.ceil(x1 * GRID / W - 0.5))
        r0, r1 = max(0, math.ceil(y0 * GRID / H - 0.5)), min(GRID, math.ceil(y1 * GRID / H - 0.5))
        if c1 > c0:
            for r in range(r0, r1):
                grid[r][c0:c1] = b"\x01" * (c1 - c0)
    return 1 - sum(sum(row) for row in grid) / (GRID * GRID)


def canvas_fill(source: dict, out: dict) -> dict:
    """Backdrop coverage and empty canvas, output vs. source.

    A full-bleed backdrop (solid fill, paper sheet, scrim or cover image)
    must keep covering the target; losing it leaves a mostly blank canvas
    with a box floating in it, which collision and font checks cannot see.
    """
    by_id = {el["id"]: el for el in out["elements"]}
    backdrops = _backdrops(source)
    shortfall = 0.0
    cover = 1.0
    for el in backdrops:
        got = coverage(aabb(by_id[el["id"]]), out["canvas"])
        expected = _expected_cover(el, out["canvas"])
        cover = min(cover, got)
        shortfall = max(shortfall, expected - got)
    return {"backdrops": len(backdrops), "backdrop_coverage": cover if backdrops else None,
            "backdrop_shortfall": shortfall, "empty_source": _empty_fraction(source),
            "empty_output": _empty_fraction(out)}


def _centroid_offset(design: dict, units: list[dict], source: dict) -> float:
    """Distance of the content's painted-area centroid from the canvas centre (canvas fractions)."""
    by_id = {el["id"]: el for el in design["elements"]}
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    total = cx = cy = 0.0
    for u in units:
        for i in u["idx"]:
            x0, y0, x1, y1 = ink_box(by_id[source["elements"][i]["id"]])
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            total += area
            cx += area * (x0 + x1) / 2
            cy += area * (y0 + y1) / 2
    if total <= 0:
        return 0.0
    return math.hypot(cx / total / W - 0.5, cy / total / H - 0.5)


def imbalance(source: dict, out: dict) -> float:
    """How much further off-centre the content mass sits than in the source."""
    units = [u for u in _units(source) if u["kind"] in ("text", "rigid") and not unavailable_unit(source, u)]
    return max(0.0, _centroid_offset(out, units, source) - _centroid_offset(source, units, source))


def _texty(source: dict, u: dict) -> bool:
    return any(source["elements"][i]["type"] == "text" for i in u["idx"])


def _side_by_side(a, b) -> bool:
    """Horizontally disjoint boxes sharing most of the shorter one's height."""
    shared = min(a[3], b[3]) - max(a[1], b[1])
    return (a[2] <= b[0] or b[2] <= a[0]) and shared >= 0.5 * min(a[3] - a[1], b[3] - b[1])


def new_text_pairs(source: dict, out: dict) -> int:
    """Copy/button units placed side by side that were not side by side in the source.

    Rows of mixed copy, pills and buttons fragment reading order; extreme
    banners need some, other formats read better as a column.
    """
    by_id = {el["id"]: el for el in out["elements"]}
    units = [u for u in _units(source) if u["kind"] in ("text", "rigid") and _texty(source, u)]
    boxes = [union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"]) for u in units]
    count = 0
    for i, u in enumerate(units):
        for j in range(i + 1, len(units)):
            if _side_by_side(boxes[i], boxes[j]) and not _side_by_side(u["bbox"], units[j]["bbox"]):
                count += 1
    return count


def _out_ink(by_id, source, idx):
    return union(ink_box(by_id[source["elements"][i]["id"]]) for i in idx)


def composition(source: dict, out: dict, units: list[dict] | None = None) -> dict:
    """Design-quality measurements that the AI judges keep pointing at.

    * margin_violation: how far content intrudes into the safe inset
      (`policy.spacing`), in margins, summed over units and edges; edges a
      unit already touched in the source are exempt.
    * containment_violations: carried content (a logo on a band, copy on a
      scrim) that left its panel, plus other content straddling a panel edge.
    * art_violation: artwork scale outside its prominence band (log units).
    * art_text_change: artwork scale drifting from the headline's scale
      beyond a free band (log units).
    * component_excess: buttons/badges outgrowing the headline scale or the
      short side (log units), ignoring legibility-driven sizes.
    * slack_imbalance: spare room split unlike the source (anchoring), as a
      share of the canvas.
    * decor_slivers: translucent decorations mostly, but not wholly, hidden
      under opaque content (reads as a glitch).
    """
    units = units if units is not None else _units(source)
    by_id = {el["id"]: el for el in out["elements"]}
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    Ws, Hs = source["canvas"]["width"], source["canvas"]["height"]
    mx, my = spacing(W, H)[:2]
    smx, smy = spacing(Ws, Hs)[:2]
    content = [u for u in units if u["kind"] in ("text", "rigid") and not unavailable_unit(source, u)]
    inks = {id(u): _out_ink(by_id, source, u["idx"]) for u in content}
    margin = 0.0
    for u in content:
        x0, y0, x1, y1 = inks[id(u)]
        sx0, sy0, sx1, sy1 = u["ink"]
        for gap, need, src_gap, src_need in ((x0, mx, sx0, smx), (y0, my, sy0, smy),
                                             (W - x1, mx, Ws - sx1, smx), (H - y1, my, Hs - sy1, smy)):
            if src_gap >= 0.5 * src_need:
                margin += max(0.0, 1 - gap / need)
    contained = 0
    for p in units:
        if p["kind"] != "panel" or not p.get("carries"):
            continue
        px0, py0, px1, py1 = union(aabb(by_id[source["elements"][i]["id"]]) for i in p["idx"])
        carried = {id(units[j]) for j in p["carries"]}
        for u in content:
            x0, y0, x1, y1 = inks[id(u)]
            area = max(1e-9, (x1 - x0) * (y1 - y0))
            share = overlap_area((x0, y0, x1, y1), (px0, py0, px1, py1)) / area
            if id(u) in carried:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                contained += not (px0 <= cx <= px1 and py0 <= cy <= py1)
            elif 0.05 < share < 0.95:
                contained += 1
    art = 0.0
    band = art_band(source, out["canvas"], units)
    for u in units:
        if tuple(u["idx"]) not in band:
            continue
        lo, hi = band[tuple(u["idx"])]
        core = u.get("core_idx", u["idx"])
        sx0, sy0, sx1, sy1 = u.get("core_ink", u["ink"])
        x0, y0, x1, y1 = _out_ink(by_id, source, core)
        scale = math.sqrt(max(1e-9, (x1 - x0) * (y1 - y0)) / max(1e-9, (sx1 - sx0) * (sy1 - sy0)))
        art += max(0.0, math.log(lo / scale)) + max(0.0, math.log(scale / hi))
    # Artwork keeps its size relative to the headline (log ratio change):
    # a logo must not dwarf the message nor shrink beside it.
    texts = [el for el in source["elements"] if el["type"] == "text"]
    art_text = 0.0
    if texts and band:
        head = max(texts, key=lambda el: (el["font_size"], -source["elements"].index(el)))
        head_scale = by_id[head["id"]]["font_size"] / head["font_size"]
        for u in units:
            if tuple(u["idx"]) not in band:
                continue
            sx0, sy0, sx1, sy1 = u.get("core_ink", u["ink"])
            x0, y0, x1, y1 = _out_ink(by_id, source, u.get("core_idx", u["idx"]))
            scale = math.sqrt(max(1e-9, (x1 - x0) * (y1 - y0)) / max(1e-9, (sx1 - sx0) * (sy1 - sy0)))
            change = math.log(scale / head_scale)
            art_text += max(0.0, -change - ART_TEXT_SLACK[0]) + max(0.0, change - ART_TEXT_SLACK[1])
    excess = 0.0
    if texts:
        head = max(texts, key=lambda el: (el["font_size"], -source["elements"].index(el)))
        head_scale = by_id[head["id"]]["font_size"] / head["font_size"]
        short = min(W, H)
        for u in content:
            els = [source["elements"][i] for i in u["idx"]]
            labels = [el for el in els if el["type"] == "text"]
            if (len(labels) != 1 or not any(el["type"] == "shape" for el in els)
                    or any(el["type"] == "image" for el in els) or labels[0] is head):
                continue
            size = by_id[labels[0]["id"]]["font_size"]
            if size <= 12:
                continue  # legibility, not inflation
            excess += max(0.0, math.log(size / labels[0]["font_size"] / head_scale / (COMPONENT_GROWTH * 1.1)))
            x0, y0, x1, y1 = inks[id(u)]
            excess += max(0.0, math.log((y1 - y0) / short / COMPONENT_SHORT))
    slack = 0.0
    if content:
        x0, y0, x1, y1 = union(inks.values())
        sx0, sy0, sx1, sy1 = union(u["ink"] for u in content)
        spread = anchor_weight(source["canvas"], out["canvas"])
        for before, after, length, src_before, src_after in ((x0 - mx, W - mx - x1, W, sx0, Ws - sx1),
                                                             (y0 - my, H - my - y1, H, sy0, Hs - sy1)):
            before, after = max(0.0, before), max(0.0, after)
            if before + after <= 1e-9:
                continue
            src_before, src_after = max(0.0, src_before), max(0.0, src_after)
            want = 0.5 if src_before + src_after <= 1e-9 else src_before / (src_before + src_after)
            want = 0.5 + (want - 0.5) * spread
            slack += abs(before / (before + after) - want) * (before + after) / length
    slivers = 0
    opaque = [(union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"]),
               max(source["elements"][i].get("z_index", i) for i in u["idx"]))
              for u in content if all(source["elements"][i]["type"] == "shape" and fill_alpha(source["elements"][i]) >= 1
                                      and source["elements"][i].get("opacity", 1) >= 1 for i in u["idx"])]
    for u in units:
        if u["kind"] != "decor":
            continue
        box = union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"])
        z = min(source["elements"][i].get("z_index", i) for i in u["idx"])
        area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
        hidden = min(1.0, sum(overlap_area(box, o) for o, oz in opaque if oz > z) / area)
        slivers += SLIVER[0] < hidden < SLIVER[1]
    return {"margin_violation": margin, "containment_violations": contained, "art_violation": art,
            "art_text_change": art_text,
            "component_excess": excess, "slack_imbalance": slack, "decor_slivers": slivers}


COMPONENT_GROWTH = 1.25  # as the row solver: components grow at most this much more than the headline
COMPONENT_SHORT = 0.26  # a one-label component taller than this share of the short side is oversized
SLIVER = (0.5, 0.98)  # hidden share of a decoration that leaves only slivers visible
ART_TEXT_SLACK = (math.log(1.5), math.log(1.6))  # free shrink / growth of art relative to the headline


def _tucked(source: dict, by_id: dict, u: dict, box, v: dict) -> bool:
    """A missing-asset placeholder hidden entirely under an opaque shape of `v` painted above it."""
    if not unavailable_unit(source, u):
        return False
    z = max(source["elements"][i].get("z_index", i) for i in u["idx"])
    for i in v["idx"]:
        m = source["elements"][i]
        if (m["type"] != "shape" or m.get("rotation", 0) or fill_alpha(m) < 1 or m.get("opacity", 1) < 1
                or m.get("z_index", i) <= z):
            continue
        x0, y0, x1, y1 = aabb(by_id[m["id"]])
        if x0 <= box[0] and y0 <= box[1] and box[2] <= x1 and box[3] <= y1:
            return True
    return False


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
    # Missing-asset units are painted as opaque placeholders by the official
    # renderer, so they count for collisions, but not for arrangement shift
    # (they are deliberately relocated to free space).
    # Collisions use painted bounds: transparent padding of art can overlap.
    boxes = [(u, union(ink_box(by_id[source["elements"][i]["id"]]) for i in u["idx"]))
             for u in _units(source) if u["kind"] not in ("bg", "decor", "panel")]
    shifts = []
    for u, box in boxes:
        if unavailable_unit(source, u):
            continue
        original = u["bbox"]
        shifts.append(math.hypot(
            (box[0] + box[2]) / (2 * out["canvas"]["width"]) - (original[0] + original[2]) / (2 * source["canvas"]["width"]),
            (box[1] + box[3]) / (2 * out["canvas"]["height"]) - (original[1] + original[3]) / (2 * source["canvas"]["height"])))
    overlaps = []
    for i, (u, a) in enumerate(boxes):
        for v, b in boxes[i + 1:]:
            area = overlap_area(a, b)
            if area > 0.5 and not _tucked(source, by_id, u, a, v) and not _tucked(source, by_id, v, b, u):
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
            "missing_assets": [im["asset_id"] for im in images if not im["available"]],
            "new_text_pairs": new_text_pairs(source, out), "imbalance": imbalance(source, out),
            "tiny_text": sum(s <= TINY_PX for s in sizes),
            **composition(source, out), **canvas_fill(source, out)}


def hierarchy_penalty(source: dict, out: dict) -> float:
    """Penalize text pairs whose size ratio collapses relative to the source.

    If A was clearly larger than B in the source, A should keep at least
    HIERARCHY_KEEP of the source ratio (in log terms); inversions cost most.
    """
    src = {el["id"]: el["font_size"] for el in source["elements"] if el["type"] == "text"}
    new = {el["id"]: max(1e-6, el["font_size"]) for el in out["elements"] if el["type"] == "text"}
    total, pairs = 0.0, 0
    ids = sorted(src, key=lambda i: -src[i])
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            if src[a] < src[b] * 1.15 or new[b] <= LEGIBLE_PX + 1:
                continue  # legibility outranks hierarchy for the smallest copy
            need = HIERARCHY_KEEP * math.log(src[a] / src[b])
            total += max(0.0, need - math.log(new[a] / new[b]))
            pairs += 1
    return total / pairs if pairs else 0.0


def inflation_penalty(source: dict, out: dict, allowed: float = 1.7) -> float:
    """Penalize secondary text (and its pill/group) growing much more than the headline.

    Scale is output/source font size; the largest source text is the reference.
    """
    src = {el["id"]: el["font_size"] for el in source["elements"] if el["type"] == "text"}
    if len(src) < 2:
        return 0.0
    ref = max(src, key=src.get)
    new = {el["id"]: el["font_size"] for el in out["elements"] if el["type"] == "text"}
    ref_scale = new[ref] / src[ref]
    excess = [max(0.0, math.log(new[i] / src[i] / ref_scale / allowed)) for i in src if i != ref]
    # Art may out-grow the headline somewhat on tall/narrow canvases, but a
    # logo should not dwarf the message (limit is looser than for text).
    src_el = {el["id"]: el for el in source["elements"]}
    for el in out["elements"]:
        o = src_el[el["id"]]
        if el["type"] == "image" and o["width"] > 0 and not is_background(o, source["canvas"]):
            excess.append(max(0.0, math.log(el["width"] / o["width"] / ref_scale / 2.0)))
    return sum(excess) / len(excess)


def choppy_penalty(out: dict, min_chars: float = 14.0) -> float:
    """Penalize copy wrapped into slivers (very few characters per line)."""
    total = 0.0
    for el in out["elements"]:
        if el["type"] != "text":
            continue
        lines, _ = measure(el, el["font_size"], el["width"])
        content = str(el.get("content", "")).strip()
        per_line = len(content) / lines
        if lines > 1 and per_line < min_chars:
            total += math.log(min_chars / max(per_line, 1))
        # A short label stacked one word per line reads as a broken column.
        if lines > 1 and len(content.split()) / lines < 1.5:
            total += 1.0
    return total


def group_area_penalty(source: dict, out: dict, allowed: float = 2.5) -> float:
    """Penalize explicit groups (pills, badges) whose share of the canvas
    grows far beyond their share in the source design."""
    src_area = source["canvas"]["width"] * source["canvas"]["height"]
    out_area = out["canvas"]["width"] * out["canvas"]["height"]
    # Extreme aspect changes force pills to occupy more of the short side.
    stretch = abs(math.log(out["canvas"]["width"] / out["canvas"]["height"]
                           * source["canvas"]["height"] / source["canvas"]["width"]))
    allowed *= math.exp(0.5 * stretch)
    by_id = {el["id"]: el for el in out["elements"]}
    excess = []
    for u in _units(source):
        if u["kind"] != "rigid" or len(u["idx"]) < 2 or u["art"]:
            continue
        x0, y0, x1, y1 = u["bbox"]
        a0, b0, a1, b1 = union(aabb(by_id[source["elements"][i]["id"]]) for i in u["idx"])
        before = (x1 - x0) * (y1 - y0) / src_area
        after = (a1 - a0) * (b1 - b0) / out_area
        if before > 0:
            excess.append(max(0.0, math.log(after / before / allowed)))
    return sum(excess) / len(excess) if excess else 0.0


TEXT_PAIR_WEIGHT = 0.2
IMAGE_WEIGHT = 0.4
LEGIBLE_PX = 9.0
TINY_PX = 7  # the official renderer mangles glyph spacing at and below this size
TINY_WEIGHT = 0.3
LEGIBLE_WEIGHT = 1.5
HEADLINE_WEIGHT = 0.5
BALANCE_WEIGHT = 2.5
BALANCE_SLACK = 0.01
HIERARCHY_KEEP = 0.85
MARGIN_WEIGHT = 0.5
CONTAINMENT_WEIGHT = 1.5
ART_WEIGHT = 0.8
COMPONENT_WEIGHT = 1.5
SLACK_WEIGHT = 1.5
SLIVER_WEIGHT = 0.5
CHOPPY_WEIGHT = 0.8
ART_TEXT_WEIGHT = 1.0


def aspect_change(source: dict, out: dict) -> float:
    """|log| of the aspect-ratio change; 0 for the same shape."""
    return abs(math.log(out["canvas"]["width"] / out["canvas"]["height"]
                        * source["canvas"]["height"] / source["canvas"]["width"]))


def score(source: dict, out: dict, q: dict | None = None) -> float:
    q = q or metrics(source, out)
    src_size = {el["id"]: el["font_size"] for el in source["elements"] if el["type"] == "text"}
    new_size = {t["id"]: max(1, t["font_size"]) for t in q["texts"]}
    readability = 0
    if src_size:
        ref = max(src_size, key=src_size.get)
        ref_scale = new_size[ref] / src_size[ref]
        canvas = math.sqrt(out["canvas"]["width"] * out["canvas"]["height"]
                           / (source["canvas"]["width"] * source["canvas"]["height"]))
        # The headline earns credit up to 2x its canvas-proportional size.
        # Supporting copy earns credit only up to 1.3x its size in proportion
        # to the headline (or a legible 16px floor); past that it merely
        # inflates its pills and crowds a wide banner.
        caps = {i: max(16, 1.3 * src_size[i] * ref_scale) for i in src_size}
        caps[ref] = max(16, 2.0 * src_size[ref] * canvas)
        sizes = [min(new_size[i], caps[i]) for i in src_size]
        # Absolute legibility matters: preserving a tiny source font ratio should
        # not beat readable supporting copy merely because a headline grew more.
        # Below a legibility floor copy is lost, not merely small: each step
        # down there costs far more than the same ratio higher up.
        # The headline should read as the headline: credit its size against
        # its canvas-proportional size, up to the same 2x cap.
        readability = (HEADLINE_WEIGHT * math.log(min(new_size[ref], caps[ref]) / max(1.0, src_size[ref] * canvas))
                       + 0.6 * math.log(min(sizes) / 12)
                       + 0.4 * sum(math.log(min(s, 96) / 12) for s in sizes) / len(sizes)
                       - LEGIBLE_WEIGHT * sum(max(0.0, math.log(LEGIBLE_PX / s)) for s in sizes) / len(sizes))
    src = {el["id"]: el for el in source["elements"]}
    # Art scale: images, and text-free shape art (a sun, a seal) that the
    # layout treats like an image; backdrops and decorations do not count.
    shape_art = {source["elements"][u["idx"][0]]["id"] for u in _units(source)
                 if u["kind"] == "rigid" and len(u["idx"]) == 1 and u["art"] and not u["images_only"]
                 and source["elements"][u["idx"][0]].get("shape_type") != "line"
                 and min(u["bbox"][2] - u["bbox"][0], u["bbox"][3] - u["bbox"][1])
                 > 0.02 * max(u["bbox"][2] - u["bbox"][0], u["bbox"][3] - u["bbox"][1])}
    images = [math.log(max(0.001, min(1.5, el["width"] / src[el["id"]]["width"])))
              for el in out["elements"] if src[el["id"]]["width"] > 0
              and ((el["type"] == "image" and not is_background(src[el["id"]], source["canvas"])
                    and asset_info(el["asset_id"])["available"]) or el["id"] in shape_art)]
    return (readability + (IMAGE_WEIGHT * sum(images) / len(images) if images else 0)
            - 4 * q["text_overflows"] - 2 * q["overlap_severity"] - TEXT_PAIR_WEIGHT * math.exp(-aspect_change(source, out)) * q["new_text_pairs"]
            - BALANCE_WEIGHT * max(0.0, q["imbalance"] - BALANCE_SLACK)
            - 3 * hierarchy_penalty(source, out) - 2 * inflation_penalty(source, out) - CHOPPY_WEIGHT * choppy_penalty(out)
            - 1.5 * group_area_penalty(source, out)
            - TINY_WEIGHT * q["tiny_text"] - MARGIN_WEIGHT * q["margin_violation"]
            - CONTAINMENT_WEIGHT * q["containment_violations"] - ART_WEIGHT * q["art_violation"]
            - COMPONENT_WEIGHT * q["component_excess"] - SLACK_WEIGHT * q["slack_imbalance"]
            - ART_TEXT_WEIGHT * q["art_text_change"]
            - SLIVER_WEIGHT * q["decor_slivers"])
