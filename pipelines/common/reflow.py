"""Shared deterministic fitting for hierarchy and multi-row flow experiments.

Every explicit group travels with one uniform transform. Rows use rotated
bounds. Impossible arrangements are discarded rather than clipped to a box.
"""

import math

from .assets import unavailable_unit
from .quality import score
from .text import measure, text_height
from .units import build_units, copy_design, place_bg, place_decor, place_rigid
from .validate import validate


def _font_size(src, el, k, gamma):
    peak = max((e["font_size"] for e in src["elements"] if e["type"] == "text"), default=24)
    return max(1, peak * k * (el["font_size"] / peak) ** gamma)


ART_GROWTH = 2.0


def _even_art(rigid, spare):
    """Grow shorter art in an image-only row toward the row height.

    A uniform scale lets a large product dwarf a wide, short logo. The row
    height is unchanged (so row selection is unaffected); smaller pieces grow
    by up to ART_GROWTH, uniformly reduced to fit the spare width.
    """
    top = max(h for _, h, _ in rigid.values())
    growth = {i: min(ART_GROWTH, top / h) if h > 0 else 1.0 for i, (_, h, _) in rigid.items()}
    extra = sum(w * (growth[i] - 1) for i, (w, _, _) in rigid.items())
    t = min(1.0, spare / extra) if extra > 1e-9 else 0.0
    grown = {}
    for i, (w, h, s) in rigid.items():
        f = 1 + t * (growth[i] - 1)
        grown[i] = (w * f, h * f, s * f)
    return grown, spare - t * extra


def _lay_row(src, units, rigid, weights, sizes, remaining, gap):
    total_weight = sum(weights.values()) or 1
    placed, height, x = [], 0, 0
    for i, u in enumerate(units):
        if i in rigid:
            w, h, s = rigid[i]
            placed.append(("rigid", u, x, 0, w, h, s))
        else:
            el = src["elements"][u["idx"][0]]
            w = remaining * weights[i] / total_weight
            lines, widest = measure(el, sizes[i], w)
            if widest > w + 1e-6:
                return None
            h = text_height(el, sizes[i], lines)
            placed.append(("text", u, x, 0, w, h, sizes[i]))
        height = max(height, h)
        x += w + gap
    return height, placed, x


def _row(src, units, width, k, gamma, gap, image_scale=1.0):
    """Fit one row at requested sizes. Return height and local placements."""
    rigid, texts = {}, []
    for i, u in enumerate(units):
        members = [src["elements"][j] for j in u["idx"]]
        if u["kind"] == "text" and not members[0].get("rotation", 0):
            texts.append(i)
        else:
            scales = [_font_size(src, e, k, gamma) / e["font_size"] for e in members if e["type"] == "text"]
            s = max(scales, default=k * (image_scale if u["images_only"] else 1.0))
            x0, y0, x1, y1 = u["bbox"]
            if u["images_only"] and len(units) == 1 and x1 > x0:
                # A lone image row may fill the width instead of blocking the
                # shared text scale: tall, narrow canvases need big art, small type.
                s = min(s, width / (x1 - x0))
            rigid[i] = ((x1 - x0) * s, (y1 - y0) * s, s)
    remaining = width - sum(v[0] for v in rigid.values()) - gap * (len(units) - 1)
    if remaining < 0 or (texts and remaining <= 0):
        return None
    if not texts and len(units) > 1 and all(u["images_only"] for u in units):
        rigid, remaining = _even_art(rigid, remaining)
    sizes, inks = {}, {}
    for i in texts:
        el = src["elements"][units[i]["idx"][0]]
        sizes[i] = _font_size(src, el, k, gamma)
        # Single-line length x line height approximates the copy's area.
        inks[i] = max(1, measure(el, sizes[i], math.inf)[1] * text_height(el, sizes[i], 1))
    # Two width splits between texts sharing a row: sqrt(area) hedges toward
    # short copy, area-proportional equalizes wrapped heights. Keep the lower.
    best = None
    for exponent in (0.5, 1.0) if len(texts) > 1 else (0.5,):
        weights = {i: inks[i] ** exponent for i in texts}
        laid = _lay_row(src, units, rigid, weights, sizes, remaining, gap)
        if laid is not None and (best is None or laid[0] < best[0] - 1e-9):
            best = laid
    if best is None:
        return None
    height, placed, x = best
    # Center rows containing only rigid units rather than anchoring left.
    offset = max(0, (width - (x - gap)) / 2) if not texts else 0
    return height, [(kind, u, px + offset, (height - h) / 2, w, h, s)
                    for kind, u, px, _, w, h, s in placed]


def _plan(src, units, rect, k, gamma, gap, mode, image_scale=1.0):
    """Dynamic programming selects contiguous rows with the least total height."""
    X, Y, W, H = rect
    n = len(units)
    if not n:
        return []
    costs, choices = [math.inf] * (n + 1), [None] * (n + 1)
    costs[0] = 0
    for end in range(1, n + 1):
        for start in range(end):
            row_units = units[start:end]
            if mode == "strip" and (start != 0 or end != n):
                continue
            if mode == "stack" and len(row_units) > 1 and any(u["kind"] == "text" for u in row_units):
                continue
            row = _row(src, row_units, W, k, gamma, gap, image_scale)
            if row is None:
                continue
            rh, placed = row
            cost = costs[start] + rh + (gap if start else 0)
            if cost < costs[end]:
                costs[end], choices[end] = cost, (start, rh, placed)
    if costs[n] > H + 1e-6:
        return None
    rows, end = [], n
    while end:
        start, rh, placed = choices[end]
        rows.append((rh, placed))
        end = start
    rows.reverse()
    # Spread leftover height between rows (bounded) rather than leaving one
    # dead block; any remainder stays centred.
    extra = min((H - costs[n]) / (len(rows) - 1), max(3 * gap, 0.04 * H)) if len(rows) > 1 else 0
    y = Y + (H - costs[n] - extra * (len(rows) - 1)) / 2
    placements = []
    for rh, row in rows:
        placements.extend((kind, u, X + x, y + py, w, h, s) for kind, u, x, py, w, h, s in row)
        y += rh + gap + extra
    return placements


def _solve(src, units, rect, gamma, gap, mode, cap, image_scale=1.0):
    placed = _plan(src, units, rect, cap, gamma, gap, mode, image_scale)
    if placed is not None:
        return placed
    lo, hi = 0.001, cap
    best = _plan(src, units, rect, lo, gamma, gap, mode, image_scale)
    if best is None:
        return None
    for _ in range(15):
        mid = (lo + hi) / 2
        placed = _plan(src, units, rect, mid, gamma, gap, mode, image_scale)
        if placed is None:
            hi = mid
        else:
            lo, best = mid, placed
    return best


def _apply(src, target, extras, placements):
    out = copy_design(src, target)
    scale = min(target["width"] / src["canvas"]["width"], target["height"] / src["canvas"]["height"])
    for u in extras:
        if u["kind"] == "bg":
            place_bg(out, u)
        else:
            place_decor(out, src, u, scale)
    for kind, u, x, y, w, h, size in placements:
        if kind == "rigid":
            place_rigid(out, src, u, size, x, y)
        else:
            m, o = src["elements"][u["idx"][0]], out["elements"][u["idx"][0]]
            o.update(x=x, y=y, width=w, height=h, font_size=size)
            if m.get("letter_spacing"):
                o["letter_spacing"] = m["letter_spacing"] * size / m["font_size"]
    return out


def candidates(src, target, mode="stack", image_scale=1.0,
               gammas=(0.65, 0.85, 1.0), split_axes=("horizontal",), defer_missing=False):
    units = build_units(src)
    if defer_missing:
        for u in units:
            if u["kind"] not in ("bg", "decor") and unavailable_unit(src, u):
                u["kind"] = "decor"
    extras = [u for u in units if u["kind"] in ("bg", "decor")]
    content = sorted((u for u in units if u["kind"] not in ("bg", "decor")),
                     key=lambda u: ((u["bbox"][1] + u["bbox"][3]) / 2, u["bbox"][0]))
    W, H = target["width"], target["height"]
    margin, gap = min(W, H) * 0.025, min(W, H) * 0.02
    rect = (margin, margin, W - 2 * margin, H - 2 * margin)
    cap = min(3, max(W / src["canvas"]["width"], H / src["canvas"]["height"]))
    solved = {}

    def solve(items, region, gamma, arrangement):
        x, y, w, h = region
        key = (tuple(tuple(u["idx"]) for u in items), w, h, gamma, arrangement)
        if key not in solved:
            solved[key] = _solve(src, items, (0, 0, w, h), gamma, gap, arrangement, cap, image_scale)
        placed = solved[key]
        return None if placed is None else [(kind, u, px + x, py + y, pw, ph, size)
                                            for kind, u, px, py, pw, ph, size in placed]

    for gamma in gammas:
        for arrangement in (mode, "strip"):
            placed = solve(content, rect, gamma, arrangement)
            if placed is not None:
                yield f"{arrangement}-{gamma}", _apply(src, target, extras, placed)
        images = [u for u in content if u["images_only"]]
        rest = [u for u in content if not u["images_only"]]
        if not images or not rest:
            continue
        # An ungrouped bottom text block can use a full-width footer, inferred
        # from geometry rather than element ids or sample annotations.
        footer = [u for u in rest if u["kind"] == "text" and u["bbox"][1] >= src["canvas"]["height"] * 0.9]
        for with_footer in (False, True) if footer else (False,):
            body = [u for u in rest if not with_footer or u not in footer]
            for fraction in (0.22, 0.35, 0.5):
                for axis, images_left in ((a, side) for a in split_axes for side in (True, False)):
                    X, Y, rw, rh = rect
                    footer_placed = []
                    if with_footer:
                        fh = rh * 0.14
                        footer_placed = solve(footer, (X, Y + rh - fh, rw, fh), gamma, "stack")
                        if footer_placed is None:
                            continue
                        rh -= fh + gap
                    if axis == "horizontal":
                        iw, tw = (rw - gap) * fraction, (rw - gap) * (1 - fraction)
                        ix, tx = (X, X + iw + gap) if images_left else (X + tw + gap, X)
                        image_rect, text_rect = (ix, Y, iw, rh), (tx, Y, tw, rh)
                    else:
                        ih, th = (rh - gap) * fraction, (rh - gap) * (1 - fraction)
                        iy, ty = (Y, Y + ih + gap) if images_left else (Y + th + gap, Y)
                        image_rect, text_rect = (X, iy, rw, ih), (X, ty, rw, th)
                    ip = solve(images, image_rect, gamma, mode)
                    tp = solve(body, text_rect, gamma, mode)
                    if ip is not None and tp is not None:
                        name = f"split-{fraction}-{'L' if images_left else 'R'}-{gamma}-footer{with_footer}"
                        if axis != "horizontal":
                            name = f"vertical-{name}"
                        yield name, _apply(src, target, extras, ip + tp + footer_placed)


def select(source, target, candidates):
    """Reject hard failures before ranking; stable iteration resolves ties."""
    best, best_score = None, -math.inf
    for name, out in candidates:
        if validate(source, target, out):
            continue
        value = score(source, out)
        if value > best_score:
            best, best_score = out, value
    if best is None:
        raise ValueError("No structurally valid layout candidate for the target")
    return best
