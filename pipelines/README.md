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
| `adaptive/` (default) | working | Adds vertical image bands, column flows for wide targets, independent art scaling, source-envelope fitting and a 0.45 hierarchy exponent. Fits overflowing group labels; ranks text overflow, a lost backdrop and unrelated overlaps before soft scores, with source-arrangement preference on nearby ratios. Returns diagnostics separately through `search()`. |
| `common/` | shared | Rotated geometry, unit classification (backdrops, frames, followers, repeated sets), group transforms, renderer-aware text metrics, structural validation, independent quality metrics, row and column reflow solvers, missing-asset placement (`placeholders.py`) and the shared target-format catalogue (`formats.py`). |

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
- Text measurement uses Skia glyph advances with the brand TTFs, matching converter wrapping, integer painted sizes, spacing and mixed font styles. Pillow remains a development fallback; real-renderer tests require the production dependencies.
- Bounded measurement caches key on copy, font/style runs, size, spacing and box width, without relying on element ids or mutable object identity. Per-size tables make one measurement linear in the number of words.
- `common/quality.py` scores absolute text readability, foreground image scale, text overflow and unrelated unit overlap. The minimum font and the mean both contribute; a large headline cannot hide tiny supporting copy. Scores are local proxies, not official challenge scores.
- `scripts/run_matrix` writes output JSONs, detailed per-text metrics, timings and `report.json`/`index.html`. `--render` calls the real renderer directly, records missing-asset warnings and PNG dimensions, and adds source/output previews. Pipeline exceptions and input mutation are recorded without poisoning later cases. Structural failures fail the run; `--strict-quality` additionally fails overflow, overlap, a lost backdrop and a mostly empty canvas. The deliberately broken stretch reference is excluded from failure counts.
- `--variants` tests renamed ids/no notes, longer copy and 35-degree groups. `--include-source` adds original canvas sizes, catching the rotated-source fallback failure. Targets are development formats, not the official catalogue.
- Tests use standard-library `unittest`; schema checks require `requirements-dev.txt`. Container execution is verified separately by the Docker track.
- Viewer add-on, solver, and local-model ideas (plan §12) are deferred; add them as separate pipelines/folders when pursued.

## Unit classification (`common/units.py`)
Every element belongs to one unit; explicit groups are always one rigid unit.
The rules are geometric and never read ids, names or annotations.

| Kind | Rule | Placement |
| --- | --- | --- |
| `bg` | Ungrouped, unrotated shape of any kind (solid fill, paper sheet, translucent scrim) covering at least 85% of the source canvas, or an unrotated cover image doing the same. | Stretched to the full target canvas. Only cover images may crop; other images keep their ratio rules. |
| `panel` (band) | Ungrouped, unrotated rectangle or line spanning at least 90% of one side and touching that edge. | Stretched along the side it spans; thickness follows the uniform canvas scale and it stays on its edge. Content is laid out clear of it unless content sat on it. |
| `panel` (sheet) | Ungrouped, unrotated opaque rectangle covering at least 25% of the canvas with two or more content units on top of it. | Mapped to the matching target region (relative margins kept); when it holds all copy, layout happens inside it. |
| `decor` | Ungrouped translucent (opacity or fill alpha below 1) or bleeding shape, except dividers (`line` shapes). | Anchored to its relative spot and clamped on-canvas, or, when it tightly wraps one content unit (at most 4x its area, covering 60% of it), moved and scaled with that unit (`follow`). |
| `text` | Ungrouped text. | Re-fitted: integer font size, wrapped, box hugging the wrapped copy. |
| `rigid` | Images, shape art and explicit groups. | One uniform transform. Units with the same member types, similar size and a shared row or column in the source form a `set` that is laid out as an even grid (all in one row, or equal rows; never 2 + 1 for three). |

Layout sizes use painted bounds (`ink_box`): transparent padding of packaged art and the empty part of a text box do not take space.
The full element box may overlap neighbours where it only holds transparent pixels, but it never leaves the canvas; art that would cross an edge shrinks about its centre, by one shared factor across a set.

## Layout search (`common/reflow.py`)
- Rows: dynamic programming over contiguous runs of units in reading order, one shared type scale `k` per solve (binary search), several hierarchy exponents.
- Columns (wide targets): the transpose, choosing contiguous columns of at most four units; each column is as narrow as its copy allows within the height.
- Splits: art beside or above copy at fixed fractions; the two blocks are then spaced evenly (edge, between, edge) so no dead gap remains between copy and art. Dividers travel with the copy.
- Footers: an ungrouped text block in the bottom 10% of the source may use a full-width footer band, sized on the body's own type scale so it never outgrows the copy above.
- Rows land near their source positions (isotonic regression); on very different aspect ratios gaps are bounded so copy reads as one block.
- A lone unit in a row or column shrinks to fit rather than blocking the shared type scale, so a wide card cannot make every headline tiny.

## Typography and the renderer
- The converter wraps at the JSON font size and cr-renderer paints at `int(font_size)`; the engine emits integer sizes (`text.paint_size`, floor, never below 1), so wrapping and painting use the same size.
- Measurement mirrors the converter's greedy wrap token by token and paints per style span: letter spacing applies between glyphs inside a span and is dropped at span boundaries, as cr-renderer does. `tests/test_canvas_and_type.py` checks this against the converter output.
- `text.tight_width` returns the narrowest box that keeps the converter's wrapping identical; reflowed text boxes use it, so alignment and centring follow the visible copy.
- Converter style-run endpoints are inclusive despite the schema's end-exclusive description. `max_lines` is not consumed by the converter.
- Skia uses the host's glyph metrics. On Linux (the scored container) FreeType hinting returns integer advances; on macOS advances are fractional. The engine measures with the same defaults as the renderer on the same host, so measurement and painting agree on each platform, but layouts can differ between a macOS venv and Docker. Judge final output from Docker renders (`scripts/docker_check.sh`).
- At 7px and below, hinted Linux advances widen letters and shrink spaces (Solstice Sans Bold at 7px: space 1px instead of 1.48px, `u` 6px instead of 4.72px), so small labels can read as `SummerLine`. This is renderer and font behavior; the score's legibility floor (8px) pushes away from such sizes where the design allows.

## Quality proxies (`common/quality.py`)
- Readability: minimum and mean font with a steep penalty below 8px, headline prominence against its canvas-proportional size, and hierarchy kept to at least 75% of the source size ratio (log terms).
- Art scale for images and text-free shape art; inflation, choppy wraps, pill area growth.
- Composition: new side-by-side copy pairs (weighted down on extreme aspect changes) and the content centroid drifting off-centre relative to the source.
- Canvas fill: backdrop coverage of the target versus what the backdrop can reach (shapes and cover images: the whole canvas), and the share of empty canvas versus the source. `--strict-quality` fails a lost backdrop or a mostly empty canvas.

## Behavior and remaining limits
- Groups retain one uniform transform; images retain their source box ratios. Rows reserve rotated unit bounds, preventing neighboring rows/groups from colliding.
- Impossible arrangements are discarded. If only the anchored candidate remains valid on an extremely small target, its text may still overflow; the report exposes this rather than claiming successful fitting.
- Tiny targets still have very small copy. Level 3 at 728x90 has eight text elements; the scored container paints its headline at 13px and its legal line at 4px. Labels inside groups cannot outgrow their pills, whose source widths total 1310px.
- In an image-only row, shorter art (typically a wide logo beside a tall product) grows up to 2x toward the row height, using only spare width.
- The renderer is the official, unmodified starter renderer: a missing asset is painted as an opaque, labeled placeholder box with a warning. Adaptive keeps fully missing image units out of content rows, then `common/placeholders.py` moves each one (rigid, ratio preserved, on-canvas, sized by the uniform canvas scale) to the free spot nearest its source anchor that clears all content, shrinking down to a 6px floor if needed. `quality.metrics` counts these units in collision checks, so a placeholder covering copy fails `--strict-quality`. Mixed groups keep their shared geometry.
- The official contain fitting pastes RGBA art with its own alpha as the mask, slightly attenuating semi-transparent edges; this is renderer behavior we do not control. Supplied asset files remain unchanged.
