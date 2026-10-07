# pipelines/

One folder per resize approach. Each exposes `resize(source, target_canvas) -> design`
in `<folder>/pipeline.py` and is registered in `pipelines/__init__.py`.
`engine/resize.py` delegates to the selected one (the starter's `engine/` layout is otherwise untouched).

| Pipeline | Status | Idea |
| --- | --- | --- |
| `baseline_stretch/` | reference | Original starter stretch. Benchmark only. |
| `anchored/` | reference + fallback | Uniform scale, centered, backgrounds fill canvas, decor clamped on-canvas. Always valid. |
| `layout_v1/` (default) | working | Groups elements into units, generates stack / strip / image+copy split layouts, fits text with real brand-font metrics, validates and scores, returns the best (anchored as floor). |
| `common/` | shared | `geometry` (rotated bounds), `text` (Pillow font measuring/fit, mirrors renderer wrapping), `units` (grouping + rigid placement), `validate` (structural proxy checks). |

```
python -m engine.main                                   # default pipeline
CHAMELEON_PIPELINE=anchored python -m engine.main       # pick one (PowerShell: $env:CHAMELEON_PIPELINE="anchored")
```

## Adding a pipeline
1. `pipelines/<name>/{__init__.py,pipeline.py}` with `resize()`.
2. Register it in `PIPELINES` in `pipelines/__init__.py`.
3. Reuse `common/`; do not import from another pipeline except `anchored` (the fallback).
4. Never add runtime network access, and never alter `content`/`font_family`/asset pixels.

## Revisions to GPT-plan.md
`GPT-plan.md` stays as the long-range reference. Changes in how we are executing it:
- Pipelines live in `pipelines/` folders, not a flat `engine/*.py` set; `engine/` stays the starter's.
- Text measurement uses Pillow with the brand TTFs (no skia import) so pipelines stay light; verify against the real renderer visually.
- Scoring/validation is deliberately small for now (`layout_v1._score`, `common/validate`). The big benchmark/HTML-report/Docker-matrix machinery (plan §9-11) is deferred until there are competing pipelines worth comparing.
- Viewer add-on, solver, and local-model ideas (plan §12) are deferred; add them as separate pipelines/folders when pursued.

## Known gaps / next steps (layout_v1)
- Tiny targets (e.g. 728x90, Level 3): one `k` scales all text, so small text becomes ~2px while the headline dominates. Needs hierarchy-aware scaling (flatten ratios so small copy keeps a floor).
- No collision avoidance for rotated groups vs. neighbors in strip mode; text-vs-text overlap only penalized in scoring.
- Decor handling is anchor-and-clamp only; label vertical alignment inside renderer boxes assumed top-aligned.
- Style runs / bold runs are measured with the base font (2% safety margin).
- Missing assets (e.g. Level 3 holiday badge) are kept as-is and treated like any rigid image.
