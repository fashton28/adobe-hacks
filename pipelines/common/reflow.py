"""Shared deterministic fitting for hierarchy and multi-row flow experiments.

Every explicit group travels with one uniform transform. Rows use rotated
bounds. Impossible arrangements are discarded rather than clipped to a box.
Text font sizes are integers (what the renderer paints); text boxes hug their
wrapped copy so spare row width is shared out instead of left as dead space.
Repeated units (cards, pills) stay together in an even grid.
"""

import math
from typing import NamedTuple

from .assets import unavailable_unit
from .geometry import overlap_area, union
from .policy import anchor_weight, art_band, spacing
from .quality import score
from .text import (
    balanced_width,
    measure,
    paint_size,
    text_height,
    text_key,
    tight_width,
)
from .units import (
    EXTRAS,
    build_units,
    clamp_unit,
    copy_design,
    panel_box,
    place_extras,
    place_rigid,
)
from .validate import validate


def _peak(src):
    return max((e["font_size"] for e in src["elements"] if e["type"] == "text"), default=24)


def _floor(fit, el):
    """Legibility floor for `el` in this solve (0 when the solve has none)."""
    return fit.floors.get(el["id"], 0.0)


def floors_for(src, units, tier, target=None):
    """Per-text legibility floors from a (headline, main label, body, tertiary) tier.

    Roles come from geometry and type only: the headline is the largest
    copy, the main label sits in the largest one-label component (a button),
    tertiary copy is small ungrouped copy (legal lines, footnotes) at most
    TERTIARY_SHARE of the headline size, which yields first. A floor never
    exceeds the source size scaled by FLOOR_GROWTH.
    """
    if not tier or not any(tier):
        return {}
    els = src["elements"]
    texts = [e for e in els if e["type"] == "text"]
    if not texts:
        return {}
    peak = max(e["font_size"] for e in texts)
    head, label, body, tertiary = tier
    labels = [u for u in units if u["kind"] == "rigid" and _label_component({"src": src}, u, els)]
    main = max(labels, key=lambda u: ((u["bbox"][2] - u["bbox"][0]) * (u["bbox"][3] - u["bbox"][1]), -min(u["idx"])),
               default=None)
    # Repeated buttons share the main label's floor (they share one scale).
    mains = [u for u in labels if u is main or (main is not None and "set" in main and u.get("set") == main["set"])]
    main_ids = {els[i]["id"] for u in mains for i in u["idx"]}
    floors = {}
    for e in texts:
        if e["font_size"] >= peak - 1e-9:
            value = head
        elif e["id"] in main_ids:
            value = label
        elif not e.get("group_id") and e["font_size"] <= TERTIARY_SHARE * peak:
            value = tertiary
        else:
            value = body
        floors[e["id"]] = min(value, e["font_size"] * FLOOR_GROWTH)
    if target is not None:
        # A group that cannot reach a floor even at the largest size the
        # canvas allows (a tall card with a tiny caption) keeps what fits,
        # instead of making every floored layout infeasible.
        W, H = target["width"], target["height"]
        for u in units:
            if u["kind"] != "rigid" or len(u["idx"]) < 2:
                continue
            x0, y0, x1, y1 = u["bbox"]
            most = 0.9 * min(W / max(x1 - x0, 1e-9), H / max(y1 - y0, 1e-9))
            for i in u["idx"]:
                e = els[i]
                if e["type"] == "text" and e["id"] in floors:
                    floors[e["id"]] = min(floors[e["id"]], math.floor(e["font_size"] * most))
    return floors


def _font_size(fit, el, k, gamma):
    """Requested (continuous) size for `el` at shared scale `k` and hierarchy `gamma`."""
    return max(1.0, _floor(fit, el), fit.peak * k * (el["font_size"] / fit.peak) ** gamma)


ART_GROWTH = 2.0
FLOOR_GROWTH = 4.0  # a legibility floor lifts copy by at most this factor over its source size
TERTIARY_SHARE = 0.35  # small ungrouped copy at most this share of the headline size is tertiary
COMPONENT_GROWTH = 1.25  # buttons and badges grow at most this much more than the headline
COMPONENT_SHORT = 0.24  # a one-label component is at most this share of the short side tall


def _even_art(rigid, spare, caps=None):
    """Grow shorter art in an image-only row toward the row height.

    A uniform scale lets a large product dwarf a wide, short logo. The row
    height is unchanged (so row selection is unaffected); smaller pieces grow
    by up to ART_GROWTH, uniformly reduced to fit the spare width.
    """
    top = max(h for _, h, _ in rigid.values())
    caps = caps or {}
    growth = {i: max(1.0, min(ART_GROWTH, top / h, caps.get(i, math.inf) / s)) if h > 0 else 1.0
              for i, (_, h, s) in rigid.items()}
    extra = sum(w * (growth[i] - 1) for i, (w, _, _) in rigid.items())
    t = min(1.0, spare / extra) if extra > 1e-9 else 0.0
    grown = {}
    for i, (w, h, s) in rigid.items():
        f = 1 + t * (growth[i] - 1)
        grown[i] = (w * f, h * f, s * f)
    return grown, spare - t * extra


class Fit(NamedTuple):
    """Fixed parameters of one solve: source, spacing, art scale and canvas size."""
    src: dict
    gap: float
    image_scale: float
    canvas: tuple[float, float]
    peak: float
    keys: dict  # element index -> text_key, computed once per solve
    spread: float  # largest gap between rows, as a fraction of the region height
    floors: dict  # element id -> legibility floor in px for this solve
    art_band: dict  # tuple(unit idx) -> (lowest, highest) scale for artwork
    anchor: float  # policy.anchor_weight: how far spare room follows the source margins
    component_ref: tuple  # (largest label size, tallest height) of one-label components: their shared scale
    memo: dict  # per-solve cache of set scales keyed by (unit idx, k, gamma)


def _label_component(fit, u, elements=None):
    """A button, pill or badge: shapes plus exactly one label, no artwork."""
    elements = elements if elements is not None else fit.src["elements"]
    els = [elements[j] for j in u["idx"]]
    return (sum(e["type"] == "text" for e in els) == 1 and any(e["type"] == "shape" for e in els)
            and not any(e["type"] == "image" for e in els))


def _component_ref(src, units):
    """(largest label size, tallest painted height) over the one-label components."""
    els = src["elements"]
    comps = [u for u in units if u["kind"] == "rigid" and _label_component(None, u, els)]
    sizes = [els[i]["font_size"] for u in comps for i in u["idx"] if els[i]["type"] == "text"]
    return max(sizes, default=0.0), max((u["ink"][3] - u["ink"][1] for u in comps), default=0.0)


def _floor_scale(fit, u):
    """Smallest scale keeping every label of a rigid unit at its legibility floor."""
    return max((_floor(fit, e) / e["font_size"] for e in (fit.src["elements"][j] for j in u["idx"])
                if e["type"] == "text"), default=0.0)


def _rigid_scale(fit, u, k, gamma):
    src = fit.src
    members = [src["elements"][j] for j in u["idx"]]
    texts = [e for e in members if e["type"] == "text"]
    # Labels must stay legible: the whole unit grows if a label needs it.
    floor = max((_floor(fit, e) / e["font_size"] for e in texts), default=0.0)
    if not texts or u.get("core_art"):
        s = k * fit.image_scale
        lo, hi = fit.art_band.get(tuple(u["idx"]), (0.0, math.inf))
        s = min(max(s, lo), hi)
        if _rule(src, u):
            # Dividers keep at least the canvas proportion, so they stay visible.
            s = max(s, min(fit.canvas) / min(src["canvas"]["width"], src["canvas"]["height"]))
    elif _label_component(fit, u):
        # Buttons, pills and badges share one scale, that of the largest label,
        # so a corner tag stays smaller than the main button as in the source.
        # They follow the headline: never more than COMPONENT_GROWTH times its
        # type scale, and never taller than COMPONENT_SHORT of the short side.
        ref, tallest = fit.component_ref
        ref = ref or max(e["font_size"] for e in texts)
        tallest = max(tallest, u["ink"][3] - u["ink"][1])
        s = min(_font_size(fit, {"id": "", "font_size": ref}, k, gamma) / ref, COMPONENT_GROWTH * k,
                COMPONENT_SHORT * min(fit.canvas) / max(tallest, 1e-9))
    else:
        s = max(_font_size(fit, e, k, gamma) / e["font_size"] for e in texts)
        s = min(s, COMPONENT_GROWTH * k)
    s = max(s, floor)
    # Layout sizes painted art; the full box (with transparent padding) must
    # still fit on the canvas so it can be kept on-canvas.
    x0, y0, x1, y1 = u["bbox"]
    return min(s, fit.canvas[0] / max(x1 - x0, 1e-9), fit.canvas[1] / max(y1 - y0, 1e-9))


def _lay_row(fit, units, rigid, weights, sizes, remaining):
    src = fit.src
    total_weight = sum(weights.values()) or 1
    placed, height = [], 0
    for i, u in enumerate(units):
        if i in rigid:
            w, h, s = rigid[i]
            placed.append(("rigid", u, w, h, s))
        else:
            el, base = src["elements"][u["idx"][0]], fit.keys[u["idx"][0]]
            w = remaining * weights[i] / total_weight
            lines, widest = measure(el, sizes[i], w, base)
            if widest > w + 1e-6:
                return None
            placed.append(("text", u, tight_width(el, sizes[i], w, base), text_height(el, sizes[i], lines), sizes[i]))
        height = max(height, placed[-1][3])
    return height, placed


def _distribute(src, placed, width, gap):
    """Lay items left to right as one centred cluster (no dead blocks).

    A lone text keeps its own alignment inside the row. Several items share
    a modestly widened gap and the cluster is centred, so spare width goes to
    the outside rather than piling up between copy and art.
    """
    used = sum(item[2] for item in placed)
    if len(placed) == 1:
        kind, u, w, _, _ = placed[0]
        align = src["elements"][u["idx"][0]].get("text_align", "left") if kind == "text" else "center"
        x = {"left": 0.0, "right": width - w}.get(align, (width - w) / 2)
        return [(x, placed[0])]
    spare = max(0.0, width - used - gap * (len(placed) - 1))
    between = gap + min(spare / (len(placed) + 1), 2 * gap)
    x = (width - used - between * (len(placed) - 1)) / 2
    out = []
    for item in placed:
        out.append((x, item))
        x += item[2] + between
    return out


def _set_block(fit, item, width, k, gamma, height=math.inf, exact=False):
    """Lay a repeated set as an even grid: all in one row, or equal rows.

    A set alone in its row or column shrinks to fit the space (`height`
    for a column) rather than blocking the shared type scale. Among the
    grids that fit, the one needing the least shrinking wins, then the
    shortest. Members share one scale and are aligned on a common edge when
    they were in the source (a left-aligned list stays a straight column).
    `exact` rejects any grid that would shrink the members.
    """
    members = item["members"]
    m = len(members)
    gap = fit.gap
    key = (tuple(item["idx"]), k, gamma)
    if key not in fit.memo:
        fit.memo[key] = (min(_rigid_scale(fit, u, k, gamma) for u in members),
                         max(_floor_scale(fit, u) for u in members),
                         [(u["ink"][2] - u["ink"][0], u["ink"][3] - u["ink"][1]) for u in members],
                         max(u["bbox"][2] - u["bbox"][0] for u in members))
    s0, floor, inks, boxed = fit.memo[key]
    widest = max(w for w, _ in inks)
    best = None
    for c in range(m, 0, -1):
        if m % c and not (m >= 5 and m % c >= c - 1):
            continue
        rows = [list(range(r, min(r + c, m))) for r in range(0, m, c)]
        unit_heights = [max(inks[i][1] for i in row) for row in rows]
        # Members never abut: c columns keep at least one block gap between them.
        s = min(s0, (width - gap * (c - 1)) / max(c * widest, 1e-9),
                (width + 2 * gap - gap * (c - 1)) / max((c - 1) * widest + boxed, 1e-9))
        n_gaps, tallest = len(rows) - 1, max(unit_heights)
        if height < math.inf:
            s = min(s, (height - gap * n_gaps) / max(sum(unit_heights), 1e-9),
                    height / max(sum(unit_heights) + SET_ROW_GAP * tallest * n_gaps, 1e-9))
        if s <= 0 or (exact and s < s0 - 1e-9) or s < floor - 1e-9:
            continue
        cell = min(width / c, widest * s + max(gap, 0.25 * widest * s)) if c > 1 else min(width, widest * s + gap)
        # Cells follow painted ink; the outer members' full boxes (labels
        # wider than their text) must still fit, give or take the margins.
        if widest * s > cell + 1e-6 or c * cell > width + 1e-6 or (c - 1) * cell + boxed * s > width + 2 * gap + 1e-6:
            continue
        # Rows sit further apart than a member's own parts, so a price reads
        # with its product rather than with the next one.
        row_gap = max(gap, SET_ROW_GAP * tallest * s)
        total = sum(unit_heights) * s + row_gap * n_gaps
        key = (-round(s, 9), total)
        if best is None or key < best[0]:
            best = (key, s, c, cell, rows, [h * s for h in unit_heights], total, row_gap)
    if best is None:
        return None
    _, s, c, cell, rows, heights, total, row_gap = best
    sizes = [(w * s, h * s) for w, h in inks]
    # A shared left edge when every member's art starts at the same offset
    # inside its box (bullets, list rows); centred cells otherwise.
    offsets = [u["ink"][0] - u["bbox"][0] for u in members]
    left = max(offsets) - min(offsets) <= 1.0 and len({round(u["bbox"][0]) for u in members}) == 1
    placed, y = [], 0.0
    for row, rh in zip(rows, heights):
        x = (width - len(row) * cell) / 2
        for i in row:
            w, h = sizes[i]
            dx = (cell - widest * s) / 2 if left else (cell - w) / 2
            placed.append(("rigid", members[i], x + dx, y + (rh - h) / 2, w, h, s))
            x += cell
        y += rh + row_gap
    return total, placed


def _row(fit, units, width, k, gamma):
    """Fit one row at requested sizes. Return height and local placements."""
    src, gap = fit.src, fit.gap
    if any(u["kind"] == "set" for u in units):
        if len(units) > 1:
            return None
        return _set_block(fit, units[0], width, k, gamma)
    rigid, texts = {}, []
    for i, u in enumerate(units):
        members = [src["elements"][j] for j in u["idx"]]
        if u["kind"] == "text" and not members[0].get("rotation", 0):
            texts.append(i)
        else:
            s = _rigid_scale(fit, u, k, gamma)
            x0, y0, x1, y1 = u["ink"]
            if len(units) == 1 and x1 > x0:
                # A lone unit may shrink to the row width instead of blocking
                # the shared type scale: narrow canvases need big art, and a
                # wide card must not make every headline tiny.
                s = min(s, width / (x1 - x0))
            if s < _floor_scale(fit, u) - 1e-9:
                return None  # shrinking would break a legibility floor
            rigid[i] = ((x1 - x0) * s, (y1 - y0) * s, s)
    remaining = width - sum(v[0] for v in rigid.values()) - gap * (len(units) - 1)
    if remaining < 0 or (texts and remaining <= 0):
        return None
    if not texts and len(units) > 1 and all(u["art"] for u in units):
        caps = {i: fit.art_band.get(tuple(units[i]["idx"]), (0.0, math.inf))[1] for i in rigid}
        rigid, remaining = _even_art(rigid, remaining, caps)
    sizes, inks = {}, {}
    for i in texts:
        el = src["elements"][units[i]["idx"][0]]
        sizes[i] = paint_size(_font_size(fit, el, k, gamma))
        # Single-line length x line height approximates the copy's area.
        inks[i] = max(1, measure(el, sizes[i], math.inf, fit.keys[units[i]["idx"][0]])[1] * text_height(el, sizes[i], 1))
    # Two width splits between texts sharing a row: sqrt(area) hedges toward
    # short copy, area-proportional equalizes wrapped heights. Keep the lower.
    best = None
    for exponent in (0.5, 1.0) if len(texts) > 1 else (0.5,):
        weights = {i: inks[i] ** exponent for i in texts}
        laid = _lay_row(fit, units, rigid, weights, sizes, remaining)
        if laid is not None and (best is None or laid[0] < best[0] - 1e-9):
            best = laid
    if best is None:
        return None
    height, placed = best
    return height, [(kind, u, x, (height - h) / 2, w, h, s)
                    for x, (kind, u, w, h, s) in _distribute(src, placed, width, gap)]


SET_ROW_GAP = 0.15  # gap between grid rows of a repeated set, share of the row height
COLUMN_ITEMS = 4  # most units stacked in one column of a column flow


def _column(fit, items, k, gamma, H):
    """Narrowest column stacking `items` within height H at scale k.

    Returns (width, height, local placements) or None. Text widths shrink
    until the stack would exceed H; art and groups keep their scale.
    """
    src, gap = fit.src, fit.gap
    fixed, texts, floor = {}, {}, 0.0
    for i, u in enumerate(items):
        if u["kind"] == "set":
            m = u["members"]
            s = min(_rigid_scale(fit, v, k, gamma) for v in m)
            floor = max(floor, min(max(v["ink"][2] - v["ink"][0] for v in m) * s, fit.canvas[0]))
            fixed[i] = None
        elif u["kind"] == "text" and not src["elements"][u["idx"][0]].get("rotation", 0):
            el, base = src["elements"][u["idx"][0]], fit.keys[u["idx"][0]]
            size = paint_size(_font_size(fit, el, k, gamma))
            texts[i] = (el, size, base)
            floor = max(floor, measure(el, size, 0, base)[1])  # longest unbreakable word
        else:
            s = _rigid_scale(fit, u, k, gamma)
            x0, y0, x1, y1 = u["ink"]
            if len(items) == 1:
                s = min(s, H / max(y1 - y0, 1e-9))
            if s < _floor_scale(fit, u) - 1e-9:
                return None  # shrinking would break a legibility floor
            fixed[i] = ((x1 - x0) * s, (y1 - y0) * s, s)
            floor = max(floor, fixed[i][0])
    if floor > fit.canvas[0]:
        return None

    def stack(width, exact=False):
        laid, total = [], gap * (len(items) - 1)
        for i, u in enumerate(items):
            if i in texts:
                el, size, base = texts[i]
                lines, widest = measure(el, size, width, base)
                if widest > width + 1e-6:
                    return None
                # A column never stacks copy one word per line (a sliver of a label).
                if lines > 1 and len(str(el.get("content", "")).split()) / lines < 1.5:
                    return None
                laid.append(("text", u, width, text_height(el, size, lines), size))
            elif fixed[i] is None:
                block = _set_block(fit, u, width, k, gamma, H if len(items) == 1 else math.inf, exact)
                if block is None:
                    return None
                laid.append(("set", u, width, block[0], block[1]))
            else:
                w, h, s = fixed[i]
                laid.append(("rigid", u, w, h, s))
            total += laid[-1][3]
        return total, laid

    lo, hi = floor, max(floor, fit.canvas[0])
    # Sets prefer a grid at their full scale; shrinking is the last resort.
    exact = any(v is None for v in fixed.values())
    top = stack(hi, exact)
    if exact and (top is None or top[0] > H + 1e-6):
        exact = False
        top = stack(hi, exact)
    if top is None or top[0] > H + 1e-6:
        return None
    best = (hi, top)
    if texts or any(v is None for v in fixed.values()):
        first = stack(lo, exact)
        if first is not None and first[0] <= H + 1e-6:
            best = (lo, first)
        else:
            for _ in range(10):
                mid = (lo + hi) / 2
                laid = stack(mid, exact)
                if laid is not None and laid[0] <= H + 1e-6:
                    hi, best = mid, (mid, laid)
                else:
                    lo = mid
    width, (height, laid) = best
    # Boxes hug their copy once the column width is settled.
    laid = [(kind, u, tight_width(texts[i][0], s, width, texts[i][2]), h, s) if kind == "text" else (kind, u, w, h, s)
            for i, (kind, u, w, h, s) in enumerate(laid)]
    # The column hugs its widest item; set grids report their own extent.
    extents = [(min(p[2] for p in item[4]), max(p[2] + p[4] for p in item[4])) if item[0] == "set"
               else (0.0, item[2]) for item in laid]
    width = max(b - a for a, b in extents)
    placed, y = [], 0.0
    for (kind, u, w, h, s), (a, b) in zip(laid, extents):
        if kind == "set":
            x_off = (width - (b - a)) / 2 - a
            placed.extend((pk, pu, px + x_off, py + y, pw, ph, ps) for pk, pu, px, py, pw, ph, ps in s)
        else:
            align = src["elements"][u["idx"][0]].get("text_align", "left") if kind == "text" else "center"
            x = {"left": 0.0, "right": width - w}.get(align, (width - w) / 2)
            placed.append((kind, u, x, y, w, h, s))
        y += h + gap
    return width, height, placed


def _plan_columns(fit, units, rect, k, gamma):
    """Dynamic programming selects contiguous columns with the least total width."""
    X, Y, W, H = rect
    n = len(units)
    costs, choices = [math.inf] * (n + 1), [None] * (n + 1)
    costs[0] = 0
    for end in range(1, n + 1):
        for start in range(max(0, end - COLUMN_ITEMS), end):
            if costs[start] == math.inf:
                continue
            col = _column(fit, units[start:end], k, gamma, H)
            if col is None:
                continue
            cost = costs[start] + col[0] + (fit.gap if start else 0)
            if cost < costs[end]:
                costs[end], choices[end] = cost, (start, col)
    if costs[n] > W + 1e-6:
        return None
    cols, end = [], n
    while end:
        start, col = choices[end]
        cols.append(col)
        end = start
    cols.reverse()
    gap = fit.gap
    extra = min((W - costs[n]) / (len(cols) + 1), 3 * gap)
    x = X + (W - costs[n] - extra * (len(cols) - 1)) / 2
    placements = []
    for width, height, placed in cols:
        y = Y + (H - height) / 2
        placements.extend((kind, u, x + px, y + py, w, h, s) for kind, u, px, py, w, h, s in placed)
        x += width + gap + extra
    return placements


def _plan(fit, units, rect, k, gamma, mode, anchor=None):
    """Dynamic programming selects contiguous rows with the least total height."""
    if mode == "columns":
        return _plan_columns(fit, units, rect, k, gamma) if units else []
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
            if mode == "stack" and len(row_units) > 1 and any(u["kind"] in ("text", "set") for u in row_units):
                continue
            if costs[start] == math.inf:
                continue
            row = _row(fit, row_units, W, k, gamma)
            if row is None:
                continue
            rh, placed = row
            cost = costs[start] + rh + (fit.gap if start else 0)
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
    rows = _align_column(fit, rows, W)
    tops = _row_tops(fit, units, rows, Y, H, fit.gap, fit.spread, anchor)
    placements = []
    for top, (rh, row) in zip(tops, rows):
        placements.extend((kind, u, X + x, top + py, w, h, s) for kind, u, x, py, w, h, s in row)
    return placements


def _align_column(fit, rows, width):
    """One alignment axis for the single-item rows of a stack.

    Left-aligned copy shares one left edge, and that column is centred as a
    block, so a paragraph is set with even inner margins instead of hugging
    the canvas edge beside centred art. Buttons and art whose source left
    edge lined up with that copy join the column; right-aligned copy does
    the same on the right. Rows holding several items keep their layout.
    """
    src = fit.src
    tol = ALIGN_TOLERANCE * src["canvas"]["width"]
    singles = [(i, row[0]) for i, (_, row) in enumerate(rows) if len(row) == 1 and row[0][0] in ("text", "rigid")]
    sides = {}
    edges = {"left": [], "right": []}
    for i, item in singles:
        u = item[1]
        if item[0] == "text":
            align = src["elements"][u["idx"][0]].get("text_align", "left")
            if align in edges:
                sides[i] = align
                edges[align].append(u["bbox"][0] if align == "left" else u["bbox"][2])
    for i, item in singles:
        if i in sides or item[0] != "rigid":
            continue
        u = item[1]
        for side, values in edges.items():
            edge = u["bbox"][0] if side == "left" else u["bbox"][2]
            if any(abs(edge - v) <= tol for v in values):
                sides[i] = side
                break
    out = list(rows)
    for side in ("left", "right"):
        members = [i for i, value in sides.items() if value == side]
        if not members:
            continue
        col = max(rows[i][1][0][4] for i in members)
        x = (width - col) / 2
        for i in members:
            rh, row = rows[i]
            kind, u, _, py, w, h, s = row[0]
            out[i] = (rh, [(kind, u, x if side == "left" else x + col - w, py, w, h, s)])
    return out


ALIGN_TOLERANCE = 0.03  # source edges this close (share of the canvas width) are one alignment axis


def _row_tops(fit, units, rows, Y, H, gap, spread=1.0, anchor=None):
    """Row tops nearest the rows' source positions, in order and inside [Y, Y + H].

    Spare height is not piled into one dead block: each row aims at its
    source centre, mapped from the units' source extent to a band, by
    isotonic regression (pool adjacent violators). On very different shapes
    the gaps are bounded (`spread`) and the band is centred, keeping copy
    together. When the solve holds the whole body, `anchor` is the source
    canvas height: the band then keeps the source content's share of the
    height and sits where the source put it (a top masthead stays near the
    top, an optically centred cluster stays centred), as far as the aspect
    change allows.
    """
    heights = [rh for rh, _ in rows]
    sy0, sy1 = min(u["bbox"][1] for u in units), max(u["bbox"][3] for u in units)
    if len(rows) == 1 and anchor is None:
        return [Y + (H - heights[0]) / 2]
    offsets, acc = [], 0.0
    for rh in heights:
        offsets.append(acc)
        acc += rh + gap
    total = acc - gap
    band = min(H, total + spread * H * (len(rows) - 1))
    frac = 0.5
    if anchor is not None:
        band = max(total, min(band, H * (sy1 - sy0) / anchor))
        before, after = max(sy0, 0.0), max(anchor - sy1, 0.0)
        if before + after > 1e-9:
            frac = 0.5 + (before / (before + after) - 0.5) * fit.anchor
    Y, H = Y + (H - band) * frac, band
    targets = []
    for (rh, row), off in zip(rows, offsets):
        centres = [(p[1]["bbox"][1] + p[1]["bbox"][3]) / 2 for p in row]
        rel = (sum(centres) / len(centres) - sy0) / max(sy1 - sy0, 1e-9)
        # Centre maps into the band its own height allows, then shifts by the
        # stacked height above it: monotone tops are then simply non-decreasing.
        targets.append(Y + rh / 2 + rel * (H - rh) - rh / 2 - off)
    blocks = []  # pool adjacent violators: [mean, count]
    for t in targets:
        blocks.append([t, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, c2 = blocks.pop()
            m1, c1 = blocks.pop()
            blocks.append([(m1 * c1 + m2 * c2) / (c1 + c2), c1 + c2])
    fitted = [m for m, c in blocks for _ in range(c)]
    lo, hi = Y, Y + H - total
    if hi < lo:
        lo = hi = Y + (H - total) / 2
    return [min(max(f, lo), hi) + off for f, off in zip(fitted, offsets)]


def _solve(fit, units, rect, gamma, mode, cap, anchor=None):
    """Largest shared scale k <= cap that fits; returns (placements, k) or None."""
    placed = _plan(fit, units, rect, cap, gamma, mode, anchor)
    if placed is not None:
        return placed, cap
    lo, hi = 0.001, cap
    best = _plan(fit, units, rect, lo, gamma, mode, anchor)
    if best is None:
        return None
    # Integer type makes k matter only in steps; 12 halvings resolve ~0.02%.
    for _ in range(12):
        mid = (lo + hi) / 2
        placed = _plan(fit, units, rect, mid, gamma, mode, anchor)
        if placed is None:
            hi = mid
        else:
            lo, best = mid, placed
    return best, lo


def _extent(placements, axis):
    lo = min(p[2 + axis] for p in placements)
    hi = max(p[2 + axis] + p[4 + axis] for p in placements)
    return lo, hi


def _shift(placements, dx, dy):
    return [(kind, u, x + dx, y + dy, w, h, s) for kind, u, x, y, w, h, s in placements]


def balance(first, second, start, length, axis):
    """Space two adjacent blocks evenly along `axis` (edge, between, edge).

    Columns are solved in fixed fractions of the canvas; their content rarely
    fills them exactly, which used to leave a dead gap between copy and art.
    """
    if not first or not second:
        return first, second
    a0, a1 = _extent(first, axis)
    b0, b1 = _extent(second, axis)
    spare = length - (a1 - a0) - (b1 - b0)
    if spare <= 0:
        return first, second
    step = spare / 3
    da = start + step - a0
    db = start + step + (a1 - a0) + step - b0
    move = (lambda d: (d, 0)) if axis == 0 else (lambda d: (0, d))
    return _shift(first, *move(da)), _shift(second, *move(db))


def _edge_fit(u, s, x, y, target):
    """Largest factor <= 1 keeping the unit's full box on canvas, scaled about its art centre."""
    ix0, iy0, ix1, iy1 = u["ink"]
    bx0, by0, bx1, by1 = u["bbox"]
    cx, cy = x + (ix1 - ix0) * s / 2, y + (iy1 - iy0) * s / 2
    reach = ((cx, ((ix0 + ix1) / 2 - bx0) * s), (target["width"] - cx, (bx1 - (ix0 + ix1) / 2) * s),
             (cy, ((iy0 + iy1) / 2 - by0) * s), (target["height"] - cy, (by1 - (iy0 + iy1) / 2) * s))
    return max(0.05, min([1.0] + [room / need for room, need in reach if need > 1e-9]))


def _edge_slide(u, s, x, y, target):
    """Shift keeping the unit's full box (art plus transparent padding) on canvas at scale s."""
    ix0, iy0, _, _ = u["ink"]
    bx0, by0, bx1, by1 = u["bbox"]
    left, top = x - (ix0 - bx0) * s, y - (iy0 - by0) * s
    right, bottom = left + (bx1 - bx0) * s, top + (by1 - by0) * s
    dx = max(0.0, -left) - max(0.0, right - target["width"])
    dy = max(0.0, -top) - max(0.0, bottom - target["height"])
    return dx, dy


def _apply(src, target, units, placements, frames=None):
    """Write placements into a fresh design; `frames` overrides panel boxes (element index -> box)."""
    out = copy_design(src, target)
    scale = min(target["width"] / src["canvas"]["width"], target["height"] / src["canvas"]["height"])
    # Repeated units share one shrink factor so a set never looks uneven.
    shared = {}
    for kind, u, x, y, w, h, size in placements:
        if kind == "rigid" and "set" in u:
            shared[u["set"]] = min(shared.get(u["set"], 1.0), _edge_fit(u, size, x, y, target))
    boxes = [(x, y, x + w, y + h) for _, _, x, y, w, h, _ in placements]
    for n, (kind, u, x, y, w, h, size) in enumerate(placements):
        if kind == "rigid":
            # Layout sized the painted art; transparent padding may extend
            # past it but never past the canvas edge. The art slides inward
            # when that clears every other block; otherwise it shrinks about
            # its centre, which cannot reach any neighbour.
            f = shared.get(u["set"]) if "set" in u else _edge_fit(u, size, x, y, target)
            fits = ((u["bbox"][2] - u["bbox"][0]) * size <= target["width"]
                    and (u["bbox"][3] - u["bbox"][1]) * size <= target["height"])
            if f < 1 and "set" not in u and fits:
                dx, dy = _edge_slide(u, size, x, y, target)
                moved = (x + dx, y + dy, x + dx + w, y + dy + h)
                if (moved[0] >= -1e-6 and moved[1] >= -1e-6 and moved[2] <= target["width"] + 1e-6
                        and moved[3] <= target["height"] + 1e-6
                        and not any(overlap_area(moved, b) > 0 for m, b in enumerate(boxes) if m != n)):
                    x, y, f = x + dx, y + dy, 1.0
                    boxes[n] = moved
            cx, cy = x + w / 2, y + h / 2
            place_rigid(out, src, u, size * f, cx - w * f / 2, cy - h * f / 2, origin="ink")
            if _rule(src, u):
                _hairline(out["elements"][u["idx"][0]])
            clamp_unit(out, u)
        else:
            m, o = src["elements"][u["idx"][0]], out["elements"][u["idx"][0]]
            # Balanced lines (no one-word orphan), re-aligned inside the slot.
            narrow = tight_width(m, size, balanced_width(m, size, w))
            if narrow < w - 1e-6:
                align = m.get("text_align", "left")
                x += {"left": 0.0, "right": w - narrow}.get(align, (w - narrow) / 2)
                w = narrow
            o.update(x=x, y=y, width=w, height=h, font_size=size)
            if m.get("letter_spacing"):
                o["letter_spacing"] = m["letter_spacing"] * size / m["font_size"]
    place_extras(out, src, units, scale)
    for i, (x0, y0, x1, y1) in (frames or {}).items():
        out["elements"][i].update(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
    return out


def _hairline(el):
    """Keep a scaled divider at least 1px thick (shapes may change their aspect)."""
    for size, pos in (("height", "y"), ("width", "x")):
        other = "width" if size == "height" else "height"
        if 0 < el[size] < 1 <= el[other]:
            el[pos] -= (1 - el[size]) / 2
            el[size] = 1.0


def _rule(src, u):
    """A thin line or bar: a divider rather than artwork."""
    if len(u["idx"]) != 1 or src["elements"][u["idx"][0]]["type"] != "shape":
        return False
    x0, y0, x1, y1 = u["bbox"]
    w, h = x1 - x0, y1 - y0
    return src["elements"][u["idx"][0]].get("shape_type") == "line" or min(w, h) <= 0.02 * max(w, h)


def content_items(units):
    """Content units in reading order, with repeated sets merged into one item."""
    content = [u for u in units if u["kind"] not in EXTRAS]
    items, sets = [], {}
    for u in content:
        if "set" in u:
            sets.setdefault(u["set"], []).append(u)
        else:
            items.append(u)
    for members in sets.values():
        if len(members) < 2:
            items.extend(members)
            continue
        # Members read along the axis they are spread on.
        xs = [u["bbox"][0] for u in members]
        ys = [u["bbox"][1] for u in members]
        horizontal = max(xs) - min(xs) >= max(ys) - min(ys)
        members = sorted(members, key=lambda u: (u["bbox"][0], u["bbox"][1]) if horizontal
                         else (u["bbox"][1], u["bbox"][0]))
        items.append({"kind": "set", "members": members, "idx": [i for u in members for i in u["idx"]],
                      "bbox": union(u["bbox"] for u in members), "ink": union(u["ink"] for u in members),
                      "art": all(u["art"] for u in members)})
    return reading_order(items)


def _cut(items, axis):
    """Split items at the first gap between their projections on `axis` (0 = x, 1 = y)."""
    ordered = sorted(items, key=lambda u: (u["bbox"][axis], u["bbox"][axis + 2], min(u["idx"])))
    reach = ordered[0]["bbox"][axis + 2]
    for n, u in enumerate(ordered[1:], 1):
        if u["bbox"][axis] >= reach - 1e-9:
            return ordered[:n], ordered[n:]
        reach = max(reach, u["bbox"][axis + 2])
    return None


def reading_order(items):
    """Source reading order by recursive row-first XY cuts.

    Rows are split at horizontal gaps; a band with no horizontal gap is split
    into columns at vertical gaps, each read top to bottom. Related copy in
    one source column (an old price above a new price) therefore stays
    consecutive even when a neighbouring column interleaves by height.
    Overlapping leftovers read by their centre, top to bottom.
    """
    if len(items) <= 1:
        return list(items)
    for axis in (1, 0):
        parts = _cut(items, axis)
        if parts:
            return reading_order(parts[0]) + reading_order(parts[1])
    return sorted(items, key=lambda u: ((u["bbox"][1] + u["bbox"][3]) / 2, u["bbox"][0], min(u["idx"])))


def content_rect(src, target, units, margin, gap):
    """Layout area: inside an inset sheet holding all copy, clear of empty edge bands.

    `margin` is one inset or an (x, y) pair.
    """
    W, H = target["width"], target["height"]
    mx, my = margin if isinstance(margin, tuple) else (margin, margin)
    x0, y0, x1, y1 = mx, my, W - mx, H - my
    content = [u for u in units if u["kind"] in ("text", "rigid")]

    def holds(panel, u):
        px0, py0, px1, py1 = panel["bbox"]
        cx, cy = (u["bbox"][0] + u["bbox"][2]) / 2, (u["bbox"][1] + u["bbox"][3]) / 2
        return px0 <= cx <= px1 and py0 <= cy <= py1

    for p in (u for u in units if u["kind"] == "panel"):
        bx0, by0, bx1, by1 = panel_box(src, p, W, H)
        inside = [u for u in content if holds(p, u)]
        if p["panel"] == "sheet" and content and len(inside) == len(content):
            pad = max(min(mx, my), 0.04 * min(bx1 - bx0, by1 - by0))
            x0, y0, x1, y1 = max(x0, bx0 + pad), max(y0, by0 + pad), min(x1, bx1 - pad), min(y1, by1 - pad)
        elif p["panel"] == "band" and not inside:
            if bx1 - bx0 >= by1 - by0:  # horizontal band: top or bottom
                if by0 <= 0.5:
                    y0 = max(y0, by1 + gap)
                elif by1 >= H - 0.5:
                    y1 = min(y1, by0 - gap)
            else:
                if bx0 <= 0.5:
                    x0 = max(x0, bx1 + gap)
                elif bx1 >= W - 0.5:
                    x1 = min(x1, bx0 - gap)
    if x1 - x0 < 0.5 * (W - 2 * mx) or y1 - y0 < 0.5 * (H - 2 * my):
        return mx, my, W - 2 * mx, H - 2 * my
    return x0, y0, x1 - x0, y1 - y0


def candidates(src, target, mode="stack", image_scale=1.0,
               gammas=(0.65, 0.85, 1.0), split_axes=("horizontal",), defer_missing=False,
               floors=None):
    units = build_units(src)
    if defer_missing:
        for u in units:
            if u["kind"] not in EXTRAS and unavailable_unit(src, u):
                u["kind"] = "decor"
                u.pop("set", None)
    content = content_items(units)
    W, H = target["width"], target["height"]
    mx, my, gap = spacing(W, H)
    rect = content_rect(src, target, units, (mx, my), gap)
    cap = min(3, max(W / src["canvas"]["width"], H / src["canvas"]["height"]))
    solved = {}
    fit = Fit(src, gap, image_scale, (W, H), _peak(src),
              {i: text_key(el) for i, el in enumerate(src["elements"]) if el["type"] == "text"},
              # Near the source shape rows may keep their source spacing;
              # far from it, gaps stay modest so copy reads as one block.
              0.06 + 0.94 * math.exp(-3 * abs(math.log(W / H * src["canvas"]["height"] / src["canvas"]["width"]))),
              floors_for(src, units, floors, target), art_band(src, target, units),
              anchor_weight(src["canvas"], target), _component_ref(src, units), {})

    def solve(items, region, gamma, arrangement, anchor=None, limit=cap):
        x, y, w, h = region
        key = (tuple(tuple(u["idx"]) for u in items), w, h, gamma, arrangement, anchor, limit)
        if key not in solved:
            solved[key] = _solve(fit, items, (0, 0, w, h), gamma, arrangement, limit, anchor)
        found = solved[key]
        return None if found is None else (_shift(found[0], x, y), found[1])

    # An ungrouped bottom text block can use a full-width footer, inferred
    # from geometry rather than element ids or sample annotations.
    footer = [u for u in content if u["kind"] == "text" and u["bbox"][1] >= src["canvas"]["height"] * 0.9]
    for gamma in gammas:
        for with_footer in (False, True) if footer else (False,):
            X, Y, rw, rh = rect
            band = None
            if with_footer:
                fh = rh * 0.14
                band = (X, Y + rh - fh, rw, fh)
                rh -= fh + gap

            def footer_for(k, band=band, gamma=gamma):
                """Footer copy on the body's own type scale, so it never outgrows it."""
                if band is None:
                    return []
                found = solve(footer, band, gamma, "stack", limit=min(cap, k))
                return None if found is None else found[0]

            body = [u for u in content if not with_footer or u not in footer]
            suffix = f"-{gamma}" + ("-footer" if with_footer else "")
            for arrangement in dict.fromkeys((mode, "strip")):
                found = solve(body, (X, Y, rw, rh), gamma, arrangement, anchor=src["canvas"]["height"])
                if found is not None and (footer_placed := footer_for(found[1])) is not None:
                    yield f"{arrangement}{suffix}", _apply(src, target, units, found[0] + footer_placed)
            # Rules and dividers separate copy: they travel with the text column.
            images = [u for u in body if u["art"] and not _rule(src, u)]
            rest = [u for u in body if not u["art"] or _rule(src, u)]
            if not images or not rest:
                continue
            for fraction in (0.22, 0.35, 0.5):
                for axis, images_left in ((a, side) for a in split_axes for side in (True, False)):
                    if axis == "horizontal":
                        iw, tw = (rw - gap) * fraction, (rw - gap) * (1 - fraction)
                        ix, tx = (X, X + iw + gap) if images_left else (X + tw + gap, X)
                        image_rect, text_rect = (ix, Y, iw, rh), (tx, Y, tw, rh)
                    else:
                        ih, th = (rh - gap) * fraction, (rh - gap) * (1 - fraction)
                        iy, ty = (Y, Y + ih + gap) if images_left else (Y + th + gap, Y)
                        image_rect, text_rect = (X, iy, rw, ih), (X, ty, rw, th)
                    ip = solve(images, image_rect, gamma, mode)
                    tp = solve(rest, text_rect, gamma, mode)
                    if ip is not None and tp is not None and (footer_placed := footer_for(tp[1])) is not None:
                        ip, tp = ip[0], tp[0]
                        first, second = (ip, tp) if images_left else (tp, ip)
                        if axis == "horizontal":
                            first, second = balance(first, second, X, rw, 0)
                        else:
                            first, second = balance(first, second, Y, rh, 1)
                        name = f"split-{fraction}-{'L' if images_left else 'R'}{suffix}"
                        if axis != "horizontal":
                            name = f"vertical-{name}"
                        yield name, _apply(src, target, units, first + second + footer_placed)
    yield from _carrier_layouts(src, target, units, content, solve, mode, gammas, (mx, my), gap)


STRIP_PAD = 0.15  # inset across a carrier strip, share of its thickness


def _carrier_layouts(src, target, units, content, solve, mode, gammas, margins, gap):
    """Layouts that keep content on the panel it sat on (copy on a scrim, a logo on a band).

    The panel carrying the most content becomes an edge strip of the target:
    a horizontal band stays on its edge; a vertical band stays vertical on
    landscape targets and turns into a top (left band) or bottom (right
    band) strip on portrait ones. Its content is laid out inside the strip,
    everything else beside it, so nothing straddles the panel edge and
    contrast (white logo on a dark band) is kept. The strip thickness is the
    band's own scaled thickness or one of a few fixed shares.
    """
    W, H = target["width"], target["height"]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    mx, my = margins
    best = None
    for p in units:
        if p["kind"] != "panel" or not p.get("carries"):
            continue
        idx = {i for j in p["carries"] for i in units[j]["idx"]}
        carried = [u for u in content if set(u["idx"]) <= idx]
        if carried and len(carried) < len(content) and (best is None or len(carried) > len(best[1])):
            best = (p, carried)
    if best is None:
        return
    panel, carried = best
    rest = [u for u in content if u not in carried]
    x0, y0, x1, y1 = panel["bbox"]
    wide = (x1 - x0) >= (y1 - y0)
    if wide:
        horizontal, first = True, y0 <= Hs - y1  # nearer the top edge
    elif W >= 0.8 * H:
        horizontal, first = False, x0 <= Ws - x1
    else:
        horizontal, first = True, x0 <= Ws - x1
    length = H if horizontal else W
    s = min(W / Ws, H / Hs)
    natural = ((y1 - y0) if wide else (x1 - x0)) * s / length
    # A band that keeps its orientation keeps its own proportion (a slim
    # footer stays slim); a re-oriented one picks among fixed shares.
    if horizontal == wide:
        shares = {round(min(max(natural, 0.08), 0.8), 3)}
        if natural >= 0.2:
            shares |= {0.3, 0.45, 0.6}
    else:
        shares = {0.3, 0.45, 0.6}
    shares = sorted(shares)
    for gamma in gammas:
        for share in shares:
            t = share * length
            # Across a slim strip the inset shrinks with it, so a logo can fill the band.
            if horizontal:
                pad = min(my, STRIP_PAD * t)
                strip = (0.0, 0.0, W, t) if first else (0.0, H - t, W, H)
                inner = (mx, strip[1] + pad, W - 2 * mx, t - 2 * pad)
                other = (mx, (t + gap) if first else my, W - 2 * mx, H - t - gap - my)
            else:
                pad = min(mx, STRIP_PAD * t)
                strip = (0.0, 0.0, t, H) if first else (W - t, 0.0, W, H)
                inner = (strip[0] + pad, my, t - 2 * pad, H - 2 * my)
                other = ((t + gap) if first else mx, my, W - t - gap - mx, H - 2 * my)
            if min(inner[2], inner[3], other[2], other[3]) <= 0:
                continue
            # The block with the most copy sets the type scale; the other never outgrows it.
            texty = sum(u["kind"] == "text" for u in carried) >= sum(u["kind"] == "text" for u in rest)
            lead, follow = (carried, rest) if texty else (rest, carried)
            lead_rect, follow_rect = (inner, other) if texty else (other, inner)
            a = solve(lead, lead_rect, gamma, mode, anchor=Hs)
            if a is None:
                continue
            b = solve(follow, follow_rect, gamma, mode, anchor=Hs, limit=a[1])
            if b is None:
                continue
            frames = {panel["idx"][0]: strip}
            yield (f"carrier-{share:g}-{'h' if horizontal else 'v'}-{gamma}",
                   _apply(src, target, units, a[0] + b[0], frames))


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
