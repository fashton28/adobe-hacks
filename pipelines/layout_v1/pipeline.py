"""layout_v1: deterministic recomposition by generating several layouts and scoring them.

Content units (text, images, explicit groups) are re-arranged rather than
stretched. Candidates:
  anchored          the uniform-scale reference (always a valid fallback)
  stack             single column of rows, in source reading order
  strip             one horizontal row (for very wide/short targets)
  split(f, side)    image column + text/button column (for wide targets)
Each candidate is validated and scored; the best valid one wins.
"""

import math
from typing import Any

from pipelines.anchored.pipeline import resize as anchored_resize
from pipelines.common.geometry import overlap_area, aabb
from pipelines.common.text import fit_text, measure, text_height
from pipelines.common.units import build_units, copy_design, place_bg, place_decor, place_rigid
from pipelines.common.validate import is_background, validate

K_MIN = 0.02
SPLIT_FRACTIONS = (0.25, 0.35, 0.45, 0.55)


# ----------------------------------------------------------------- helpers

def _bounds(src, u):
    x0, y0, x1, y1 = u["bbox"]
    return x1 - x0, y1 - y0


def _rows(units):
    """Group rigid units that share a horizontal band; text units stand alone."""
    rows: list[list[dict]] = []
    for u in sorted(units, key=lambda u: ((u["bbox"][1] + u["bbox"][3]) / 2, u["bbox"][0])):
        if rows and u["kind"] == "rigid" and rows[-1][0]["kind"] == "rigid":
            r = rows[-1]
            y0, y1 = min(m["bbox"][1] for m in r), max(m["bbox"][3] for m in r)
            ov = min(y1, u["bbox"][3]) - max(y0, u["bbox"][1])
            if ov >= 0.5 * min(y1 - y0, u["bbox"][3] - u["bbox"][1]):
                r.append(u)
                continue
        rows.append([u])
    for r in rows:
        r.sort(key=lambda m: m["bbox"][0])
    return rows


def _text_el(src, u):
    return src["elements"][u["idx"][0]]


# ----------------------------------------------------------------- solvers
# Each solver returns (feasible, placements). A placement is
#   ("rigid", unit, scale, x, y)  or  ("text", unit, x, y, w, h, size)

def _stack(src, units, rect, k, gap):
    X, Y, W, H = rect
    built, total = [], 0.0
    for row in _rows(units):
        if row[0]["kind"] == "text":
            el = _text_el(src, row[0])
            size, h = fit_text(el, W, math.inf, el["font_size"] * k)
            built.append(("text", row[0], size, h))
            total += h
        else:
            sumw = sum(_bounds(src, u)[0] for u in row)
            r = min(k, (W - gap * (len(row) - 1)) / sumw) if sumw else k
            r = max(r, K_MIN * 0.1)
            rh = r * max(_bounds(src, u)[1] for u in row)
            built.append(("row", row, r, rh))
            total += rh
    total += gap * (len(built) - 1)
    feasible = total <= H + 1e-6
    extra = 0.0
    if feasible and len(built) > 1:
        extra = min((H - total) / (len(built) - 1), 2 * gap)
    y = Y + max(0.0, (H - total - extra * (len(built) - 1)) / 2)
    placed = []
    for item in built:
        if item[0] == "text":
            _, u, size, h = item
            placed.append(("text", u, X, y, W, h, size))
            y += h
        else:
            _, row, r, rh = item
            rw = sum(_bounds(src, u)[0] * r for u in row) + gap * (len(row) - 1)
            x = X + (W - rw) / 2
            for u in row:
                bw, bh = _bounds(src, u)
                placed.append(("rigid", u, r, x, y + (rh - bh * r) / 2))
                x += bw * r + gap
            y += rh
        y += gap + extra
    return feasible, placed


def _strip(src, units, rect, k, gap):
    X, Y, W, H = rect
    units = sorted(units, key=lambda u: u["bbox"][0])
    rigid = [u for u in units if u["kind"] == "rigid"]
    texts = [u for u in units if u["kind"] == "text"]
    scales = {id(u): min(k, H / max(_bounds(src, u)[1], 1e-6)) for u in rigid}
    rigid_w = sum(_bounds(src, u)[0] * scales[id(u)] for u in rigid)
    avail = W - rigid_w - gap * (len(units) - 1)
    if texts and avail <= 4 * len(texts):
        return False, []
    nat = {}
    for u in texts:
        el = _text_el(src, u)
        nat[id(u)] = math.sqrt(max(measure(el, el["font_size"] * k, 1e9)[1], 1.0))
    tot = sum(nat.values()) or 1.0
    feasible, placed, x = True, [], X
    for u in units:
        if u["kind"] == "rigid":
            s = scales[id(u)]
            bw, bh = _bounds(src, u)
            placed.append(("rigid", u, s, x, Y + (H - bh * s) / 2))
            x += bw * s + gap
        else:
            el = _text_el(src, u)
            w = avail * nat[id(u)] / tot
            size, h = fit_text(el, w, H, el["font_size"] * k)
            feasible &= size >= el["font_size"] * k * 0.999
            placed.append(("text", u, x, Y + (H - min(h, H)) / 2, w, min(h, H), size))
            x += w + gap
    return feasible, placed


def _solve(solver, src, units, rect, gap, kcap):
    """Largest scale k <= kcap for which `solver` is feasible (binary search)."""
    if not units:
        return []
    ok, placed = solver(src, units, rect, kcap, gap)
    if ok:
        return placed
    lo, hi, best = K_MIN, kcap, None
    ok, placed = solver(src, units, rect, lo, gap)
    best = placed
    if ok:
        for _ in range(16):
            mid = (lo + hi) / 2
            ok, placed = solver(src, units, rect, mid, gap)
            if ok:
                lo, best = mid, placed
            else:
                hi = mid
    return best


# ----------------------------------------------------------------- candidates

def _apply(src, target, units, placements, extras):
    out = copy_design(src, target)
    for u in extras:
        if u["kind"] == "bg":
            place_bg(out, u)
    s_decor = min(target["width"] / src["canvas"]["width"], target["height"] / src["canvas"]["height"])
    for u in extras:
        if u["kind"] == "decor":
            place_decor(out, src, u, s_decor)
    for p in placements:
        if p[0] == "rigid":
            _, u, s, x, y = p
            place_rigid(out, src, u, s, x, y)
        else:
            _, u, x, y, w, h, size = p
            o, m = out["elements"][u["idx"][0]], src["elements"][u["idx"][0]]
            o["x"], o["y"], o["width"], o["height"] = x, y, w, h
            o["font_size"] = size
            if m.get("letter_spacing"):
                o["letter_spacing"] = m["letter_spacing"] * size / m["font_size"]
    return out


def _score(src, out) -> float:
    ratios, weights, img, overlap = [], [], [], 0.0
    boxes = []
    sel = {e["id"]: e for e in src["elements"]}
    for o in out["elements"]:
        m = sel[o["id"]]
        if o["type"] == "text":
            ratios.append(min(1.5, max(0.01, o["font_size"] / m["font_size"])))
            weights.append(m["width"] * m["height"] + 1)
        elif o["type"] == "image" and not is_background(m, src["canvas"]) and m["width"]:
            img.append((min(1.5, max(0.01, o["width"] / m["width"])), m["width"] * m["height"]))
        if o["type"] != "shape" or o.get("group_id"):
            if not is_background(m, src["canvas"]):
                boxes.append((o.get("group_id") or o["id"], aabb(o)))
    text_term = 0.0
    if ratios:
        wmean = sum(w * math.log(r) for r, w in zip(ratios, weights)) / sum(weights)
        text_term = 0.5 * math.log(min(ratios)) + 0.5 * wmean
    img_term = sum(a * math.log(r) for r, a in img) / sum(a for _, a in img) if img else 0.0
    area = out["canvas"]["width"] * out["canvas"]["height"]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i][0] != boxes[j][0]:
                overlap += overlap_area(boxes[i][1], boxes[j][1])
    return text_term + 0.5 * img_term - 4 * overlap / area


def _candidates(src, target):
    W, H = target["width"], target["height"]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    units = build_units(src)
    extras = [u for u in units if u["kind"] in ("bg", "decor")]
    content = [u for u in units if u["kind"] in ("text", "rigid")]
    if not content:
        return
    m = 0.04 * min(W, H)
    gap = 0.03 * min(W, H)
    rect = (m, m, W - 2 * m, H - 2 * m)
    kcap = max(W / Ws, H / Hs)

    yield "stack", _apply(src, target, units, _solve(_stack, src, content, rect, gap, kcap), extras)
    yield "strip", _apply(src, target, units, _solve(_strip, src, content, rect, gap, kcap), extras)

    imgs = [u for u in content if u["images_only"]]
    rest = [u for u in content if not u["images_only"]]
    if imgs and rest:
        for f in SPLIT_FRACTIONS:
            for images_left in (True, False):
                lw = (rect[2] - gap) * f
                rw = rect[2] - gap - lw
                lrect = (rect[0], rect[1], lw, rect[3])
                rrect = (rect[0] + lw + gap, rect[1], rw, rect[3])
                if not images_left:
                    lrect, rrect = (rect[0] + rw + gap, rect[1], lw, rect[3]), (rect[0], rect[1], rw, rect[3])
                placed = _solve(_stack, src, imgs, lrect, gap, kcap) + _solve(_stack, src, rest, rrect, gap, kcap)
                yield f"split{f}{'L' if images_left else 'R'}", _apply(src, target, units, placed, extras)


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    ref = anchored_resize(source, target_canvas)
    best, best_score = ref, _score(source, ref) - (100 if validate(source, target_canvas, ref) else 0)
    for _name, cand in _candidates(source, target_canvas):
        score = _score(source, cand) - (100 if validate(source, target_canvas, cand) else 0)
        if score > best_score:
            best, best_score = cand, score
    return best
