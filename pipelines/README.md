# pipelines/

One folder per resize approach. Each exposes `resize(source, target_canvas) -> design`
in `<folder>/pipeline.py` and is registered in `pipelines/__init__.py`.
`engine/resize.py` delegates to the selected one (the starter's `engine/` layout is otherwise untouched).

| Pipeline | Status | Idea |
| --- | --- | --- |
| `baseline_stretch/` | reference | Original starter stretch. Benchmark only. |
| `anchored/` | reference + fallback | Uniform scale, centered, backgrounds fill canvas, decor clamped on-canvas. Always valid. |
| `layout_v1/` | reference | Original stack / strip / image+copy split search with source-size-ratio scoring. Retained for comparison. |
| `hierarchy/` | experiment | Stacks, strips, splits and inferred full-width footers; compresses font-size ratios so supporting copy receives more space. |
| `flow/` | working | Includes hierarchy candidates plus dynamic programming for multiple rows, choosing row breaks for arbitrary counts of groups/text/images. Rejects invalid candidates before quality ranking. |
| `adaptive/` (default) | working | Adds vertical image bands, independent image scaling, source-envelope fitting and a 0.45 hierarchy exponent. Fits overflowing group labels; ranks text overflow and unrelated overlaps before soft scores, with source-arrangement preference on nearby ratios. Returns diagnostics separately through `search()`. |
| `common/` | shared | Rotated geometry, group transforms, renderer-aware text metrics, structural validation, independent quality metrics, reflow solvers, missing-asset placement (`placeholders.py`) and the shared target-format catalogue (`formats.py`). |

## Programmatic API

`pipelines/api.py` is the stable entry point for tools such as the web viewer:

```python
from pipelines.api import run
result = run(source, {"width": 728, "height": 90}, pipeline=None)
# {"output": design, "validation": [errors], "metrics": {...}, "score": float,
#  "pipeline": "adaptive", "elapsed_ms": float}
```

`pipeline=None` uses `CHAMELEON_PIPELINE` or `DEFAULT`.
Inputs are never mutated; invalid input or an unknown pipeline raises `ValueError`.
The result keys are a public contract covered by `tests/test_api.py`.

## Commands

```
python -m engine.main                                   # default pipeline
CHAMELEON_PIPELINE=anchored python -m engine.main       # pick one (PowerShell: $env:CHAMELEON_PIPELINE="anchored")
python -m unittest discover -s tests -v
python -m scripts.run_matrix --render --include-source
python -m scripts.run_matrix --pipelines hierarchy flow --variants --check-determinism --strict-quality
```

## Adding a pipeline
1. `pipelines/<name>/{__init__.py,pipeline.py}` with `resize()`.
2. Register it in `PIPELINES` in `pipelines/__init__.py`.
3. Reuse `common/`; do not import from another pipeline except `anchored` (the fallback).
4. Never add runtime network access, and never alter `content`/`font_family`/asset pixels.

## Revisions to GPT-plan.md
`GPT-plan.md` stays as the long-range reference. Changes in how we are executing it:
- Pipelines live in `pipelines/` folders, not a flat `engine/*.py` set; `engine/` stays the starter's.
- Text measurement now uses Skia glyph advances with the brand TTFs, matching converter wrapping, integer painted sizes, spacing and mixed font styles. Pillow remains a development fallback; real-renderer tests require the production dependencies.
- A bounded measurement cache keys on copy, font/style runs, size, spacing and box width, reducing repeated row-search work without relying on element ids or mutable object identity.
- `common/quality.py` scores absolute text readability, foreground image scale, text overflow and unrelated unit overlap. The minimum font and the mean both contribute; a large headline cannot hide tiny supporting copy. Scores are local proxies, not official challenge scores.
- `scripts/run_matrix` writes output JSONs, detailed per-text metrics, timings and `report.json`/`index.html`. `--render` calls the real renderer directly, records missing-asset warnings and PNG dimensions, and adds source/output previews. Pipeline exceptions and input mutation are recorded without poisoning later cases. Structural failures fail the run; `--strict-quality` additionally fails overflow/overlap. The deliberately broken stretch reference is excluded from failure counts.
- `--variants` tests renamed ids/no notes, longer copy and 35-degree groups. `--include-source` adds original canvas sizes, catching the rotated-source fallback failure. Targets are development formats, not the official catalogue.
- Tests use standard-library `unittest`; schema checks require `requirements-dev.txt`. Container execution is verified separately by the Docker track.
- Viewer add-on, solver, and local-model ideas (plan §12) are deferred; add them as separate pipelines/folders when pursued.

## Behavior and remaining limits
- New pipelines use font hierarchy exponents 0.65, 0.85 and 1.0. Groups retain one uniform transform; images retain their source box ratios. Rows reserve rotated unit bounds, preventing neighboring rows/groups from colliding.
- The anchored reference now translates rotated groups back on canvas together and reduces oversized units uniformly. Only unrotated cover images covering at least 85% of the source canvas qualify for background cropping; large contain/fill images keep their ratio checks.
- Impossible arrangements are discarded. If only the anchored candidate remains valid on an extremely small target, its text may still overflow; the report exposes this rather than claiming successful fitting.
- Tiny targets can still have unreadable copy. Level 3 at 728x90 improves from about 2.3px minimum (`layout_v1`) to 5.7px (`flow`) and 5.9px (`adaptive`, headline 10.2px). One shared scale drives all fonts and the four pills alone need 1310px of source width, so pill labels cannot exceed about 8.3px there. These are diagnostic thresholds, not submission requirements; inspect text baked into image assets separately.
- Texts sharing a row try two width splits (sqrt of copy area, and proportional to copy area, which equalizes wrapped heights) and keep the shorter row.
- In an image-only row, shorter art (typically a wide logo beside a tall product) grows up to 2x toward the row height, using only spare width; row height and row selection are unchanged.
- Converter style-run endpoints are inclusive despite the schema's end-exclusive description. Measurement mirrors the actual converter; source run indices remain untouched. `max_lines` is not consumed by the converter.
- Decorations still use anchor-and-clamp placement. Ranking favors readable copy, which can enlarge labels/CTAs and reduce product prominence; inspect real previews alongside scores.
- The renderer is the official, unmodified starter renderer: a missing asset is painted as an opaque, labeled placeholder box with a warning. Adaptive keeps fully missing image units out of content rows, then `common/placeholders.py` moves each one (rigid, ratio preserved, on-canvas, sized by the uniform canvas scale) to the free spot nearest its source anchor that clears all content, shrinking down to a 6px floor if needed. `quality.metrics` counts these units in collision checks, so a placeholder covering copy fails `--strict-quality`. Mixed groups keep their shared geometry.
- The official contain fitting pastes RGBA art with its own alpha as the mask, slightly attenuating semi-transparent edges; this is renderer behavior we do not control. Supplied asset files remain unchanged. Quality reports include visible image dimensions so padded product/logo assets can be reviewed at their actual painted size.
