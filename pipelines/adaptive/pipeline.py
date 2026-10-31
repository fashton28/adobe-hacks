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
from pipelines.common.reflow import candidates, content_rect, spacing
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


def _anchor(before: float, after: float) -> float:
    """Share of spare room that goes before the content, as in the source."""
    before, after = max(before, 0.0), max(after, 0.0)
    return 0.5 if before + after < 1e-9 else before / (before + after)


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
    mx, my, gap = spacing(W, H)
    X, Y, rw, rh = content_rect(source, target, units, (mx, my), gap)
    scale = min(3, rw / max(x1 - x0, 1e-9), rh / max(y1 - y0, 1e-9))
    # Spare room is split like the source's own margins, so a masthead that
    # sat at the top stays near the top instead of drifting to the middle.
    Ws, Hs = source["canvas"]["width"], source["canvas"]["height"]
    fx, fy = _anchor(x0, Ws - x1), _anchor(y0, Hs - y1)
    tx, ty = X + (rw - (x1 - x0) * scale) * fx, Y + (rh - (y1 - y0) * scale) * fy
    out = copy_design(source, target)
    for u in content:
        place_rigid(out, source, u, scale, tx + (u["bbox"][0] - x0) * scale,
                    ty + (u["bbox"][1] - y0) * scale)
    place_extras(out, source, units, min(W / source["canvas"]["width"], H / source["canvas"]["height"]))
    return out


# Legibility floors in px for (headline, main button label, other copy, tertiary
# copy), from comfortable to the last resort; tertiary copy yields first.
FLOOR_TIERS = ((13, 11, 10, 9), (11, 10, 9, 8), (11, 10, 8, 0), (10, 9, 7, 0), (10, 8, 7, 0), (10, 7, 6, 0))
FLOOR_TRIGGER = 10.0  # add floored candidates when uniform scaling would paint copy below this


def _needs_floors(source, target):
    s = min(target["width"] / source["canvas"]["width"], target["height"] / source["canvas"]["height"])
    sizes = [e["font_size"] for e in source["elements"] if e["type"] == "text"]
    return bool(sizes) and min(sizes) * s < FLOOR_TRIGGER


def _candidates(source, target, state=None):
    """Candidate layouts; `state["best_min_font"]` (kept by search) lets floored passes be skipped."""
    state = state if state is not None else {}
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
    # Severe downscales: keep every text at a legible floor wherever a
    # layout allows it, instead of shrinking all copy by one factor.
    if _needs_floors(source, target) and state.get("best_min_font", 0) < FLOOR_TRIGGER:
        modes = ("stack", "flow") + (("columns",) if target["width"] > target["height"] else ())
        for tier in FLOOR_TIERS:
            produced = False
            for mode in modes:
                for image_scale in (1.0, 0.55):
                    for name, out in candidates(source, target, mode=mode, image_scale=image_scale,
                                                gammas=(0.45, 0.65, 0.85), floors=tier,
                                                split_axes=("horizontal", "vertical"), defer_missing=True):
                        produced = True
                        yield f"floor{tier[0]}-{mode}-images{image_scale}-{name}", out
            if produced:
                break  # lower tiers only when nothing fits at this one


def search(source: dict, target_canvas: dict) -> tuple[dict, dict]:
    """Return the selected design and diagnostics without polluting its schema.

    Never raises for a usable input: when no candidate passes validation, the
    one with the fewest structural problems is returned (a batch must not
    lose every later task to one odd design).
    """
    validate_input(source, target_canvas)
    best, best_rank, selected = None, None, None
    fallback, fallback_key = None, None
    evaluated, rejected, error = 0, 0, None
    source_ratio = source["canvas"]["width"] / source["canvas"]["height"]
    target_ratio = target_canvas["width"] / target_canvas["height"]
    # A modest ratio change should preserve composition when feasible;
    # extreme banners need much more freedom to move the furniture.
    intent_weight = INTENT_WEIGHT * math.exp(-2 * abs(math.log(target_ratio / source_ratio)))
    state = {"best_min_font": 0}
    generator = _candidates(source, target_canvas, state)
    while True:
        try:
            name, candidate = next(generator)
            out = place_missing_assets(_fit_labels(candidate), source)
        except StopIteration:
            break
        except Exception as exc:  # noqa: BLE001 - one broken generator must not lose the task
            error = f"{type(exc).__name__}: {exc}"
            break
        evaluated += 1
        problems = validate(source, target_canvas, out)
        if problems:
            rejected += 1
            if fallback_key is None or len(problems) < fallback_key:
                fallback, fallback_key = (name, out), len(problems)
            continue
        q = metrics(source, out)
        value = score(source, out, q)
        if not q["text_overflows"]:
            state["best_min_font"] = max(state["best_min_font"], q["min_font"])
        if not math.isfinite(value):
            rejected += 1
            continue
        rank = (-q["text_overflows"], -(q["backdrop_shortfall"] > BACKDROP_SLACK), -q["overlap_severity"],
                value - intent_weight * q["layout_shift"])
        if best_rank is None or rank > best_rank:
            best, best_rank, selected = out, rank, name
    if best is None:
        if fallback is None:
            raise ValueError("No layout candidate for the target")
        selected, best = fallback
    return best, {"selected": selected, "evaluated": evaluated,
                  "rejected": rejected, "fallback": selected == "anchored" or best_rank is None,
                  "valid": best_rank is not None, "error": error, "intent_weight": intent_weight}


def resize(source: dict, target_canvas: dict) -> dict:
    return search(source, target_canvas)[0]
