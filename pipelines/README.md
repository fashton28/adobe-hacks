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
| `common/` | shared | Rotated geometry, group transforms, renderer-aware text metrics, structural validation, independent quality metrics and reflow solvers. |

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
- Tests use standard-library `unittest`; schema checks require `requirements-dev.txt`. Docker execution remains unverified here because Docker is unavailable.
- Viewer add-on, solver, and local-model ideas (plan §12) are deferred; add them as separate pipelines/folders when pursued.

## Behavior and remaining limits
- New pipelines use font hierarchy exponents 0.65, 0.85 and 1.0. Groups retain one uniform transform; images retain their source box ratios. Rows reserve rotated unit bounds, preventing neighboring rows/groups from colliding.
- The anchored reference now translates rotated groups back on canvas together and reduces oversized units uniformly. Only unrotated cover images covering at least 85% of the source canvas qualify for background cropping; large contain/fill images keep their ratio checks.
- Impossible arrangements are discarded. If only the anchored candidate remains valid on an extremely small target, its text may still overflow; the report exposes this rather than claiming successful fitting.
- Tiny targets can still have unreadable copy. Level 3 at 728x90 improves from about 2.3px minimum (`layout_v1`) to 5.7px (`flow`) and 5.9px (`adaptive`). These are diagnostic thresholds, not submission requirements; inspect text baked into image assets separately.
- Converter style-run endpoints are inclusive despite the schema's end-exclusive description. Measurement mirrors the actual converter; source run indices remain untouched. `max_lines` is not consumed by the converter.
- Decorations still use anchor-and-clamp placement. Ranking favors readable copy, which can enlarge labels/CTAs and reduce product prominence; inspect real previews alongside scores.
- Missing assets retain their JSON elements and warnings but paint transparently. Adaptive defers fully missing image units from content rows; mixed groups keep their shared geometry. `show_missing_assets=True` enables diagnostic placeholders in the converter/renderer.
- Contain fitting copies RGBA pixels without applying their alpha twice, preserving transparent edges. Supplied asset files remain unchanged. Quality reports include visible image dimensions so padded product/logo assets can be reviewed at their actual painted size.
