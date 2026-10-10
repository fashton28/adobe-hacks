# Tested strategies

## Banner visual correction (2026-10-10)

The Level 3 wide banner exposed two gaps in numerical evaluation: a missing
badge's error placeholder was painted as content, and the product's baked-in
Solstice lettering became too small. Missing artwork now paints transparently
while retaining its JSON element and warning; diagnostic placeholders remain
available through `show_missing_assets=True`. Adaptive defers fully missing
image units from content rows and excludes them from visible quality penalties.

At 1600x400 the bottle box increases from about 233px to 298px; its visible
artwork width increases from about 99px to 127px. Contain fitting also stops
applying alpha twice, preserving antialiased edges. Source asset hashes remain
unchanged. Reports now expose visible image sizes and missing asset names;
embedded lettering still requires native-size visual review.

All 36 regression tests pass. A scoped 36-case sample/stress evaluation with
schema, contract, overflow, overlap, mutation and repeated-call determinism
checks has zero gated failures (`output/visual_fix_stress`). The previous
144-case evaluation below predates this correction. At 728x90 the revised
adaptive minimum text size is about 5.9px, with one element below 6px.

## Adaptive search revision (2026-10-10)

`adaptive` is now the default. It adds vertical image bands, independently
scaled images, a stronger supporting-copy hierarchy option, source-envelope
fitting, and a source-arrangement preference that decreases on extreme aspect
changes. It rejects invalid outputs before ranking and fits overflowing group
labels without moving their geometry separately from the group.

Measured minimum text sizes before the banner visual correction:

| Sample / target | `layout_v1` | `flow` | `adaptive` |
| --- | ---: | ---: | ---: |
| Level 1 / 1080x1350 | 37.5px | 47.8px | 54.9px |
| Level 2 / 1600x400 | 24.7px | 38.4px | 40.7px |
| Level 3 / 728x90 | 2.3px | 5.7px | 6.1px |

The advanced banner has no text below 6px with `adaptive`, but all eight text
elements are below 10px. This trades some headline size for supporting copy;
it is not a universal readability win. Rotated/long-copy stress variants can
still require text below 6px. Real previews retain every asset and string,
including the deliberately missing holiday image's renderer placeholder.

Validation evidence:

- All 32 regression tests pass. Coverage includes contract failures, group transforms, source
  mutation, fresh-process determinism, id renaming, array reordering,
  renderer metrics, text fitting, cache correctness and report failure gates.
- The adaptive sample/stress matrix has 144 cases,
  including original canvases, with zero contract/schema violations, measured
  text overflow or unrelated unit overlaps. The separately repeated-call run
  is saved to `output/final_eval`.
- Independent development designs: 24 combinations, all contract/schema,
  measured overflow/overlap and repeated-call checks pass, with real PNGs in
  `output/final_independent`. These are development fixtures, not held-out data.
- Visual comparison: `output/final_review/index.html`, nine public sample/size
  combinations across four approaches. Native-size previews were inspected
  for the three actual requested targets. `python -m engine.main` also passes;
  its three JSONs validate against the schema and PNGs match target dimensions.

A bounded cache now reuses text measurements by typography values, including
style runs and spacing. Tests compare it with uncached measurements after
property changes; the advanced target's selected JSON is unchanged. The full
matrix timings were collected before this cache and should not be treated as
final performance measurements. The cached engine smoke run took about 0.2s,
1.3s and 7.8s on this machine while other evaluations were running.

See `EVALUATION.md` for reproducible commands, readable-subset gates, visual
acceptance and a frozen held-out corpus strategy. Docker remains unverified
because it is unavailable here. All scores and thresholds are local proxies.

## 2026-10-10: hierarchy and multi-row flow

Added `hierarchy` (font hierarchy compression with stacks/splits/footers) and
`flow` (also chooses multi-row breaks with dynamic programming). `flow` is now
the default. The existing `layout_v1` remains a comparison reference.

Shared fixes: anchored placement keeps rotated groups on canvas; background
cropping exemptions require an unrotated, near-full-bleed cover image; validation
checks preserved assets/styles/ids and rejects collapsed/nonfinite geometry.
Text measurement uses the renderer's Skia advances and wrapping behavior,
including integer paint sizes, letter spacing and inclusive converter run ends.
Cached typefaces own their font data, avoiding borrowed-buffer lifetime failures
on Windows during long sweeps. No source imagery or renderer code changed.

Evaluation used the repository's Python 3.11 environment and real renderer:

- `python -m unittest discover -s tests -v`: **20 tests pass**, including an
  independent design with five groups, renamed/reordered ids, repeated/fresh-process
  determinism, rotated bounds, missing assets and converter measurement checks.
- All five compared strategies across 3 samples x (11 development targets +
  original canvas): **180 cases**. Non-stretch strategies have zero structural
  failures. `layout_v1`, `hierarchy` and `flow` have zero measured text overflow
  and unrelated-unit overlap. Anchored retains source-layout overlaps.
- New-strategy stress sweep: originals plus renamed ids/no notes, longer copy,
  and 35-degree groups, across the same 12 targets: **288 cases**. Zero structural,
  overflow, overlap, mutation or repeated-call determinism failures with
  `--check-determinism --strict-quality`.
- Real-rendered comparison of `layout_v1`, `hierarchy`, `flow` across four
  representative targets: **36 output PNGs**, plus source renders. Reviewed native
  sample-target previews; missing holiday artwork retains the expected placeholder.
- Default `python -m engine.main`: all three JSON/PNG pairs pass validation and
  have the exact target dimensions. No new production dependencies or top-level
  runtime directories; the existing Docker copies include both new pipelines.

Minimum font sizes at the given sample targets:

| Sample / target | layout_v1 | hierarchy | flow |
| --- | ---: | ---: | ---: |
| Level 1 / 1080x1350 | 37.5px | 47.8px | 47.8px |
| Level 2 / 1600x400 | 24.7px | 30.4px | 38.4px |
| Level 3 / 728x90 | 2.3px | 4.1px | 5.7px |

On the new absolute-readability/overflow/overlap proxy (`common/quality.py`),
`flow` scores above `layout_v1` in all **36** public source/target cases.
This score differs from the historical source-ratio proxy below and is **not
an official score**. Level 3 still has three text elements below 6px (versus
seven for `layout_v1`); complete-copy fitting does not imply comfortable
readability. Label/CTA prominence can increase at the expense of product size.

Reproduce the reports:

```text
python -m scripts.run_matrix --pipelines stretch anchored layout_v1 hierarchy flow --include-source --output-dir output/full_matrix
python -m scripts.run_matrix --pipelines hierarchy flow --variants --include-source --check-determinism --strict-quality --output-dir output/stress
python -m scripts.run_matrix --pipelines layout_v1 hierarchy flow --targets leaderboard banner_wide instagram_portrait medium_rect --render --output-dir output/comparison
```

Each writes `report.json` and an HTML `index.html`, with per-text metrics and
output JSONs; the rendered report adds clickable native-size PNGs. Reports are
git-ignored. Docker remains **unverified** because Docker is not installed here.

## Earlier baseline evaluation

Running log of what we've tried on the three given samples (`input/`), and how it went.
Python 3.11 (matches Docker), real renderer (`renderer/converter`). Docker itself not yet built/run.

## How "evaluation" was done so far
- **Structural checks** (`pipelines/common/validate.py`): same ids, nothing off-canvas, foreground image ratio within ~5%, content/font_family unchanged, finite values. All three samples pass for `layout_v1`.
- **Proxy score** (`layout_v1._score`): our own heuristic — keeps font/image sizes close to source, penalises overlaps. **Not the official rubric** (weights unknown).
- **Visual inspection** of the rendered PNGs by eye. No source-vs-output side-by-side yet.
- **Extra sweep** (`python -m scripts.run_matrix`): 3 samples x 11 invented common sizes x 3 pipelines. `layout_v1` scored higher than `anchored` in 32 of 33 combos (one near-tie: Level 3 → Instagram post, -0.31 vs -0.34) with no structural problems. Proxy scores only; these PNGs were not reviewed.

## Pipelines

| Pipeline | Result |
| --- | --- |
| `baseline_stretch` | Starter stretch. Distorts everything; benchmark only. |
| `anchored` | Uniform scale + center. Always valid except when the source itself bleeds (Level 3 rotated ribbon → off-canvas at 1080x1350). Text gets small on wide targets. Used as fallback. |
| `layout_v1` (default) | Groups elements, tries stack / strip / image+copy split layouts, fits text with brand-font metrics, picks best-scoring valid candidate. |

## `layout_v1` per sample

| Sample | Target | Observations |
| --- | --- | --- |
| Level 1 warmup | 1080x1350 | Valid and clean, text readable. Sun logo smallish, layout sparse with lots of empty space. Source render not compared, so unclear if that matches intent. |
| Level 2 core | 1600x400 | Best result. Bottle left; badge, headline, subhead, CTA stacked right; groups intact; text readable. Subhead sits close to CTA; decorative circle behind CTA looks slightly off. |
| Level 3 advanced | 728x90 | Valid but weak. Headline readable, other text ~2-3px (one scale factor shrinks all text). Ribbon overlaps neighbours. |

Pattern across the sweep: tall/square/moderately wide targets are fine; very small or extreme formats (728x90, 160x600, 300x250) score poorly for the same shrunken-text reason.

## Not yet verified
- Bold/coloured style runs are measured with the base font (+2% margin).
- Renderer text placement assumed top-aligned within its box.
- Real Docker build / `--network none` run.
- Official rubric, target catalogue, and image-ratio tolerance.

## Next
1. Hierarchy-aware text sizing so small copy keeps a floor on tiny targets (Level 3).
2. Side-by-side source vs output renders for all three samples.
3. Collision handling for rotated groups in strip mode.

## Where to see the images
Generated by `python -m engine.main` (git-ignored, so regenerate locally):
- `output/chameleon_sample_level1_warmup_output.png`
- `output/chameleon_sample_level2_core_output.png`
- `output/chameleon_sample_level3_advanced_output.png`

Sweep renders: `python -m scripts.run_matrix --render` → `output/matrix/<level>_<target>_<pipeline>.png`.
