"""
THIS IS THE FILE YOU IMPLEMENT.

Everything else in this repo (input loading, output writing, rendering,
the Dockerfile) is plumbing so you can focus on exactly one function:
`resize()`. See RULES.md and the design schema for the full contract.
"""

from typing import Any


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        source: {"canvas": {"width": int, "height": int}, "elements": [...]}
                 — the design at its original size. See
                 chameleon_design_schema_v0.9.json for the full element spec
                 (text / image / shape, position, size, rotation, opacity,
                 z_index, group_id, and type-specific fields).
        target_canvas: {"width": int, "height": int} — the shape you're
                 resizing into.

    Returns:
        A design dict with the SAME shape as `source`:
        {"canvas": target_canvas, "elements": [...]}

        Hard requirements (see RULES.md for the full list):
        - Every element `id` in `source` must appear exactly once in your
          output. Do not add, remove, or invent elements.
        - Do not regenerate or redraw any asset's pixel content — you are
          repositioning and resizing the elements you were given, nothing
          more. This is a disqualifying rule, not a style preference.
        - Non-background image elements should be kept in proportion
          (matching the source aspect ratio within ~5%) unless they are a
          full-bleed / `fit: "cover"` element, which is expected to crop.
        - `font_size` may change to help text fit. `font_family` and
          `content` should not, for this stage of scoring (see RULES.md,
          "Adaptive typography and copy").
        - Nothing should end up outside `target_canvas`'s bounds.

    This is where your actual approach goes: constraint solving, a learned
    layout model, heuristics, whatever you choose. Latency is not a scoring
    concern (see RULES.md) — spend your effort on quality, not speed.
    """

    # ------------------------------------------------------------------
    # Naive baseline so this file runs out of the box. This is a uniform
    # stretch — literally the thing the brief tells you NOT to do ("a
    # naive program stretches the picture; a good one moves the
    # furniture"). It's here so `python -m engine.main` produces valid,
    # schema-correct output on day one. Replace the body of this function;
    # do not just tune these three lines.
    # ------------------------------------------------------------------
    scale_x = target_canvas["width"] / source["canvas"]["width"]
    scale_y = target_canvas["height"] / source["canvas"]["height"]

    out_elements = []
    for el in source["elements"]:
        el = dict(el)  # shallow copy — don't mutate the input
        el["x"] = el["x"] * scale_x
        el["y"] = el["y"] * scale_y
        el["width"] = el["width"] * scale_x
        el["height"] = el["height"] * scale_y
        if el["type"] == "text":
            # font_size scaling isn't required to be uniform — this is
            # just a starting point. Floored at 1px: the schema requires
            # font_size >= 1, and an extreme downscale (e.g. a tall poster
            # squeezed into a short banner) can otherwise compute < 1.
            el["font_size"] = max(1.0, el["font_size"] * min(scale_x, scale_y))
        out_elements.append(el)

    return {
        "canvas": {"width": target_canvas["width"], "height": target_canvas["height"]},
        "elements": out_elements,
    }
