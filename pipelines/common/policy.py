"""Shared layout policy: safe margins, block gaps and artwork prominence bands.

Generators use these to build layouts and `quality` uses the same numbers to
score them, so the ranking measures what the layouts aim for. Everything is
derived from canvas geometry and element types, never from ids or names.
"""

import math

MARGIN = 0.04  # safe inset, share of the short side
MARGIN_MIN_PX = 6.0
GAP = 0.025  # minimum gap between blocks, share of the short side
GAP_MIN_PX = 4.0
ART_MIN_PX = 40.0  # smallest visible side of secondary art (a logo) where the canvas allows
ART_MIN_SHORT = 0.3  # ... but never more than this share of the short side


def spacing(W, H):
    """Safe margins (x, y) and the minimum gap between blocks for a W x H canvas.

    One proportional inset for every non-background element: about 4% of the
    short side (at least 6px on tiny formats), and up to 3% of each side
    along long axes, so copy never touches an edge. Gaps grow with the
    canvas too.
    """
    short = min(W, H)
    base = max(MARGIN * short, min(MARGIN_MIN_PX, 0.07 * short))
    gap = max(GAP * short, min(GAP_MIN_PX, 0.05 * short))
    return max(base, min(0.03 * W, 2.5 * base)), max(base, min(0.03 * H, 2.5 * base)), gap


def anchor_weight(src_canvas, target):
    """How strongly spare room follows the source's own margins (1 at the same shape).

    Near the source aspect ratio a top masthead stays at the top and an
    optically centred cluster stays centred; on extreme changes the content
    block is simply centred.
    """
    change = abs(math.log(target["width"] / target["height"] * src_canvas["height"] / src_canvas["width"]))
    return math.exp(-change)


def art_band(src, target, units):
    """Lowest and highest scale per artwork unit, relative to the short sides.

    The largest artwork (the hero) may grow up to 2.5x the short-side ratio
    and keeps at least 0.9x of it; secondary art (logos, seals) stays within
    0.8x to 1.5x of it, so a logo can neither dwarf the message nor shrink
    into an unreadable mark. Small art also keeps a legible absolute size.
    """
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    W, H = target["width"], target["height"]
    ratio = min(W, H) / min(Ws, Hs)
    els = src["elements"]
    # Images only: shape art (rules, discs) has no legible size to protect.
    art = [u for u in units if u["kind"] == "rigid" and (u["art"] or u.get("core_art"))
           and any(els[i]["type"] == "image" for i in u.get("core_idx", u["idx"]))]
    if not art:
        return {}
    core = {id(u): u.get("core_ink", u["ink"]) for u in art}
    area = {id(u): (core[id(u)][2] - core[id(u)][0]) * (core[id(u)][3] - core[id(u)][1]) for u in art}
    hero = max(art, key=lambda u: (area[id(u)], -min(u["idx"])))
    band = {}
    for u in art:
        x0, y0, x1, y1 = core[id(u)]
        side = max(min(x1 - x0, y1 - y0), 1e-9)
        legible = min(ART_MIN_PX, ART_MIN_SHORT * min(W, H)) / side
        if u is hero:
            band[tuple(u["idx"])] = (max(0.9 * ratio, legible), max(2.5 * ratio, legible))
        else:
            band[tuple(u["idx"])] = (max(0.8 * ratio, legible), max(1.5 * ratio, legible))
    return band
