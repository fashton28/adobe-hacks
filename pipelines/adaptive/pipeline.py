"""Bounded layout search with independent image scale and safe text fitting.

Groups retain a uniform geometry transform; overflowing labels may reduce
their font size without changing their content, styles or group placement.
Hard validity gates precede ranking. Text overflow and unrelated overlaps
take priority over the soft readability/image-size proxy.
"""

import math

from pipelines.anchored.pipeline import resize as anchored_resize
from pipelines.common.assets import unavailable_unit
from pipelines.common.geometry import union
from pipelines.common.placeholders import place_missing_assets
from pipelines.common.quality import BACKDROP_SLACK, metrics, score
from pipelines.common.reflow import candidates, content_rect
from pipelines.common.text import fit_text
from pipelines.common.units import build_units, copy_design, place_extras, place_rigid
from pipelines.common.validate import validate, validate_input

INTENT_WEIGHT = 2.0  # preference for the source arrangement at the same aspect ratio


def _fit_labels(out):
    """Shrink any label that overflows its box (in place; candidates are fresh copies)."""
    for el in out["elements"]:
        if el["type"] != "text":
            continue
        previous_size = el["font_size"]
        size, _ = fit_text(el, el["width"], el["height"], previous_size)
        el["font_size"] = size
        if el.get("letter_spacing"):
            el["letter_spacing"] *= size / previous_size
    return out


def _preserved(source, target):
    """Fit the occupied source envelope while keeping the original arrangement."""
    units = build_units(source)
    for u in units:
        if u["kind"] not in ("bg", "decor", "panel") and unavailable_unit(source, u):
            u["kind"] = "decor"
    content = [u for u in units if u["kind"] not in ("bg", "decor", "panel")]
    if not content:
        return anchored_resize(source, target)
    x0, y0, x1, y1 = union(u["bbox"] for u in content)
    W, H = target["width"], target["height"]
    # Same layout area as the reflowed candidates: inside an inset sheet
    # that holds the copy, clear of empty edge bands.
    X, Y, rw, rh = content_rect(source, target, units, min(W, H) * 0.025, min(W, H) * 0.02)
    scale = min(3, rw / max(x1 - x0, 1e-9), rh / max(y1 - y0, 1e-9))
    tx, ty = X + (rw - (x1 - x0) * scale) / 2, Y + (rh - (y1 - y0) * scale) / 2
    out = copy_design(source, target)
    for u in content:
        place_rigid(out, source, u, scale, tx + (u["bbox"][0] - x0) * scale,
                    ty + (u["bbox"][1] - y0) * scale)
    place_extras(out, source, units, min(W / source["canvas"]["width"], H / source["canvas"]["height"]))
    return out


def _candidates(source, target):
    yield "anchored", anchored_resize(source, target)
    yield "preserved", _preserved(source, target)
    yield from candidates(source, target, mode="stack", defer_missing=True)
    # Art may grow independently of type; width-limited lone images saturate.
    for name, out in candidates(source, target, mode="stack", image_scale=3.0, defer_missing=True):
        yield f"big-images-{name}", out
    for image_scale in (1.0, 0.55):
        for name, out in candidates(source, target, mode="flow", image_scale=image_scale,
                                    gammas=(0.45, 0.65, 0.85, 1.0),
                                    split_axes=("horizontal", "vertical"), defer_missing=True):
            yield f"flow-images{image_scale}-{name}", out
    # Column flow suits wide banners: copy wraps narrow beside art and buttons.
    if target["width"] > target["height"]:
        for image_scale in (1.0, 0.55):
            for name, out in candidates(source, target, mode="columns", image_scale=image_scale,
                                        gammas=(0.45, 0.65, 0.85, 1.0), defer_missing=True):
                yield f"columns-images{image_scale}-{name}", out


def search(source: dict, target_canvas: dict) -> tuple[dict, dict]:
    """Return the selected design and diagnostics without polluting its schema."""
    validate_input(source, target_canvas)
    best, best_rank, selected = None, None, None
    evaluated, rejected = 0, 0
    source_ratio = source["canvas"]["width"] / source["canvas"]["height"]
    target_ratio = target_canvas["width"] / target_canvas["height"]
    # A modest ratio change should preserve composition when feasible;
    # extreme banners need much more freedom to move the furniture.
    intent_weight = INTENT_WEIGHT * math.exp(-2 * abs(math.log(target_ratio / source_ratio)))
    for name, candidate in _candidates(source, target_canvas):
        evaluated += 1
        out = place_missing_assets(_fit_labels(candidate), source)
        if validate(source, target_canvas, out):
            rejected += 1
            continue
        q = metrics(source, out)
        value = score(source, out, q)
        if not math.isfinite(value):
            rejected += 1
            continue
        rank = (-q["text_overflows"], -(q["backdrop_shortfall"] > BACKDROP_SLACK), -q["overlap_severity"],
                value - intent_weight * q["layout_shift"])
        if best_rank is None or rank > best_rank:
            best, best_rank, selected = out, rank, name
    if best is None:
        raise ValueError("No structurally valid layout candidate for the target")
    return best, {"selected": selected, "evaluated": evaluated,
                  "rejected": rejected, "fallback": selected == "anchored",
                  "intent_weight": intent_weight}


def resize(source: dict, target_canvas: dict) -> dict:
    return search(source, target_canvas)[0]
