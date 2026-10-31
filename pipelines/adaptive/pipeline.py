"""Bounded layout search with independent image scale and safe text fitting.

Groups retain a uniform geometry transform; overflowing labels may reduce
their font size without changing their content, styles or group placement.
Hard validity gates precede ranking. Text overflow and unrelated overlaps
take priority over the soft readability/image-size proxy.
"""

import copy
import math

from pipelines.anchored.pipeline import resize as anchored_resize
from pipelines.common.assets import unavailable_unit
from pipelines.common.geometry import union
from pipelines.common.placeholders import place_missing_assets
from pipelines.common.quality import metrics, score
from pipelines.common.reflow import candidates
from pipelines.common.text import fit_text
from pipelines.common.units import (
    build_units,
    copy_design,
    place_bg,
    place_decor,
    place_rigid,
)
from pipelines.common.validate import validate, validate_input


def _fit_labels(out):
    out = copy.deepcopy(out)
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
        if u["kind"] not in ("bg", "decor") and unavailable_unit(source, u):
            u["kind"] = "decor"
    content = [u for u in units if u["kind"] not in ("bg", "decor")]
    if not content:
        return anchored_resize(source, target)
    x0, y0, x1, y1 = union(u["bbox"] for u in content)
    W, H = target["width"], target["height"]
    margin = min(W, H) * 0.025
    scale = min(3, (W - 2 * margin) / max(x1 - x0, 1e-9),
                (H - 2 * margin) / max(y1 - y0, 1e-9))
    tx, ty = (W - (x1 - x0) * scale) / 2, (H - (y1 - y0) * scale) / 2
    out = copy_design(source, target)
    for u in units:
        if u["kind"] == "bg":
            place_bg(out, u)
        elif u["kind"] == "decor":
            place_decor(out, source, u, scale)
        else:
            place_rigid(out, source, u, scale, tx + (u["bbox"][0] - x0) * scale,
                        ty + (u["bbox"][1] - y0) * scale)
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


def search(source: dict, target_canvas: dict) -> tuple[dict, dict]:
    """Return the selected design and diagnostics without polluting its schema."""
    validate_input(source, target_canvas)
    best, best_rank, selected = None, None, None
    evaluated, rejected = 0, 0
    source_ratio = source["canvas"]["width"] / source["canvas"]["height"]
    target_ratio = target_canvas["width"] / target_canvas["height"]
    # A modest ratio change should preserve composition when feasible;
    # extreme banners need much more freedom to move the furniture.
    intent_weight = 3 * math.exp(-2 * abs(math.log(target_ratio / source_ratio)))
    for name, candidate in _candidates(source, target_canvas):
        evaluated += 1
        out = place_missing_assets(_fit_labels(candidate), source)
        if validate(source, target_canvas, out):
            rejected += 1
            continue
        q = metrics(source, out)
        value = score(source, out)
        if not math.isfinite(value):
            rejected += 1
            continue
        rank = (-q["text_overflows"], -q["overlap_severity"], value - intent_weight * q["layout_shift"])
        if best_rank is None or rank > best_rank:
            best, best_rank, selected = out, rank, name
    if best is None:
        raise ValueError("No structurally valid layout candidate for the target")
    return best, {"selected": selected, "evaluated": evaluated,
                  "rejected": rejected, "fallback": selected == "anchored",
                  "intent_weight": intent_weight}


def resize(source: dict, target_canvas: dict) -> dict:
    return search(source, target_canvas)[0]
