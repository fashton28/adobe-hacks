# Tested strategies

## Engine round 4: fidelity constraints from the blind review (2026-10-31)

Driven by the round-3 judges (`output/review/round3_judges_and_review.json`): blind `tests/heldout3` averaged 3.7 against 5.1 on the seen `tests/heldout2`, and every blind failure was a broken relationship.
`tests/heldout3` is now development data.
All rules are geometric and read no ids, names or notes.

What changed:
- `common/fidelity.py` measures relationships on a small z-aware raster of source and output (renderer paint order, fills, opacity, downsampled asset pixels): new occlusion of copy and art, text contrast against its actual backdrop for every style-run colour, images camouflaged on a same-coloured backdrop, content shapes losing distinctness, and content escaping its container.
  These are ranked right after text overflow and a lost backdrop in `adaptive.search` (hard constraints whenever any candidate satisfies them); the raster only runs for candidates that could still win, so search time stayed about flat.
- Containment composites, overlapping-art motifs, concentric ring followers with a shared shrink, bridges (a badge between two cards), bleeding decorations flush in their edge or corner, opaque decorations that yield to copy, and set grids that never abut (details in `pipelines/README.md`).
- Faithfulness first: `preserved-edges` re-anchors units that hugged a source edge; `preserved` candidates get a bonus fading out at a 1.6x aspect change.
- Soft terms: split stacked copy or rules (`separated`, 0.5 each) and a top or bottom logo drifting to mid-height (`logo_adrift`, 0.4).
- Columns never wrap a label one word per line.
- Robustness: zero-size text boxes made the official renderer reject the output (reproduced through `pipelines.api.run`); they now get a 1px box, and a non-positive `line_height` becomes 1.0.
  A fuzz loop (500 random designs with rotated groups, missing assets, text only, tiny and huge canvases, elements outside the canvas, zero sizes) found the `line_height` case and a regression in the first box fix; after the fixes all 500 validate and render with the official renderer.
  `tests/test_robustness.py` and the new `tests/test_fidelity.py` cover these.

Per task at the requested target (macOS venv selection, container renders reviewed at native size):
- heldout3_02 newsletter card: the email field and button stay inside the cream card next to logo and bottle; no fidelity violation (round 3: field and CTA on the dark background, 3 violations); copy is still small (minimum 4px).
- heldout3_05 product comparison: NEW stays on its card and VS sits between the stacked cards (round 3: both stray); the logo still sits alone in a side gutter.
- heldout3_07 discount coupon: everything stays inside the coupon with full contrast, but the rigid coupon is only 128px wide in 160x600, so copy paints at 1 to 16px; round 3 was legible but broke the coupon and lost the orange `OFF` on orange.
  A legible fix needs the coupon frame to stretch out of its group transform, which the group contract does not allow today.
- heldout3_08 seasonal greeting: the message is no longer covered; sun, rings and bottle stay one concentric motif on the right, hills sit small in the bottom corners, the logo sits under the motif.
- heldout3_04 testimonial: the name moved back above its role (round 3 split them across the canvas); the accent rule still floats under the quote.
- heldout3_03 launch countdown: cards keep a gutter (round 3: 0px); the bottom fifth is still empty and the logo docks beside the product.
- heldout3_01 menu special and 06 festival lineup: unchanged apart from a smaller corner moon; 01 copy stays 5 to 8px, 06 keeps its mixed alignments.
- heldout_04 editorial columns: the white logo stays on its dark footer band (round 3: invisible on cream) in a three-column layout.
- heldout2_06 minimal brand: the accent rule sits with the tagline again.
- Level 1: `preserved` wins (logo back near its top margin, headline 75 to 70px); Level 2: centred copy column with the product and logo at right, logo still small; Level 3 unchanged.
  Other seen tasks keep their round-3 layout.

Remaining weaknesses:
- The hard fidelity tier can choose a much less legible layout when only that one satisfies it (07 at 160x600; heldout_04 at 300x250 picks `anchored` with 2px copy to keep the logo on its band).
- Mixed alignments inside columns (06), floating accent rules (01, 04), small logos (Level 2) and tiny copy on 728x90 remain.
- I opened `tests/heldout4` by accident once (a glob over `tests/*/*.json` printed composite detections for four of its tasks); nothing was tuned on it, but it is no longer fully blind for this track.

## Engine round 3: design-quality rules from the AI-judge review (2026-10-31)

Driven by the independent review of round-2 container outputs (`output/review/round2_judges_and_review.json`).
`tests/heldout` and `tests/heldout2` were used as development data; `tests/heldout3` was not opened.
All rules are geometric and read no ids, names or notes.

Robustness:
- `units.panel_box` clamped each corner separately, so a band lying wholly outside the source canvas got a negative width and every candidate failed (reproduced, regression test in `tests/test_robustness.py`).
  Each axis is now clamped as an interval and the band keeps its own thickness.
- Every element's unrotated x/y/width/height box stays on canvas as well as its rotated bounds (`geometry.extent`); `validate` checks both, matching the starter `self_check`.
- `adaptive.search` never raises for a usable input: if no candidate validates it returns the one with the fewest problems, and a broken generator keeps the candidates found so far.
- A zero line height is accepted (layout reserves 1.0 lines).

Layout rules:
- Safe margins from `policy.spacing`: 4% of the short side (at least 6px), up to 3% of each long side, and larger block gaps.
- Legibility floors per role (headline, main button label, other copy, tertiary copy such as legal lines) in tiers from (13, 11, 10, 9) down to (10, 7, 6, 0); a tier is tried only when uniform scaling would paint copy below 10px and no layout is already legible, and lower tiers only when nothing fits.
  Shrink-to-fit paths may not break a floor; groups that cannot reach a floor at any canvas-fitting size keep what fits.
- Buttons, pills and badges share one scale (that of the largest label), never more than 1.25x the headline scale and never taller than 24% of the short side, so a corner tag stays smaller than the main button.
- Artwork prominence bands (`policy.art_band`): the hero image keeps 0.9x to 2.5x of the short-side ratio, secondary images (logos) 0.8x to 1.5x, both with a legible minimum (40px or 30% of the short side).
- Relationships: an edge band inside a group becomes its own band; a badge, stamp or tag overlapping a larger unit below it is merged with that host (a sticker stays attached at its corner); panels record the content painted on them, and carrier layouts keep that content inside the panel's strip (logo on a footer band, copy on a scrim).
- Reading order by recursive row-first XY cuts, so an old price stays next to its new price.
- Whole-body row bands keep the source content's share of the height and sit where the source put them (anchor weight `exp(-|log aspect change|)`); `preserved` splits spare room like the source margins.
- Single-item rows of a stack share one alignment axis: left-aligned copy (and buttons aligned with it in the source) forms one centred column.
- Repeated sets: the least-shrinking grid wins, list rows share a left edge, and grid rows sit 15% of a row apart, so a price reads with its own product.
- Line balancing (no one-word orphans), dividers at least 1px thick and at canvas scale, padded art slides inward before shrinking, decorations that would leave slivers under an opaque button move clear.
- Missing-asset placeholders are tucked fully under an opaque button or panel painted above them when one exists, otherwise placed at the smallest legal size.

Scoring (`quality.composition`): margin violations, containment violations, art outside its band, art drifting from the headline scale, component excess, slack split unlike the source, decoration slivers, text at or below 7px, one-word-per-line wraps; legibility floor 9px; hierarchy keep 0.85 but ignored for copy at or below 10px.
These are reported in every matrix row; none became a `--strict-quality` gate because none is always satisfiable (the anchored fallback can violate all of them).

Container minimum painted font, round 2 to round 3: Level 1 38 to 41, Level 2 26 to 19 (subhead now held below the headline), Level 3 4 to 6 (headline 11, button 7, badges 6), editorial 23 to 23, typography 16 to 11, product trio 31 to 28, sparse decor 30 to 30, accented copy 26 to 25, editorial columns 19 to 18, layered groups 25 to 16, severe downscale 7 to 9, event poster 13 to 14, sale banner 12 to 7, app promo 3 to 3 (a caption inside a tall card group cannot grow without breaking the group), quote card 37 to 42, product grid 25 to 23, minimal brand 6 to 10, layered sticker 34 to 22, infographic 16 to 15.
Lower minimums are mostly hierarchy fixes (secondary copy no longer inflated); inspect the PNGs.

Visual notes from container renders: the quote card keeps the white logo on its dark band; the layered sticker becomes a top scrim band with the copy and the bottle below with its sticker attached; badges stay on their product or panel corner; the infographic list is a straight two-column grid; the minimal brand card stays optically centred; the sale banner reads 40% OFF, then the old and new price together.

Remaining weaknesses:
- 728x90 with many texts still paints supporting copy at 6-7px on Linux, where hinting mangles spacing (the rotated ribbon reads `SUNSETSALE`).
- Groups keep one transform, so a small caption inside a tall card (app promo rating) stays at 3px on a leaderboard.
- Wide banners from text-heavy portraits (typography fixture) still prefer a stacked column over a horizontal arrangement by a small score margin.
- The product grid header puts the logo alone in a side column; corner anchoring for small corner tags (Level 2 badge) is not implemented.
- Floored tiers add time on tiny targets: Level 3 takes 2.2s in the container (round 2: 1.95s); every development task stays under 2.3s.

## Engine round 2: canvas fill, painted type, columns and sets (2026-10-30)

Round 1 left four failure classes, all fixed with geometric rules that read no ids or names.

Backdrops and frames:
- Any ungrouped, unrotated shape covering at least 85% of the source canvas (solid field, paper sheet, translucent scrim) is now a backdrop and stretches to the full target; cover images keep the old rule.
- Edge bands stretch along their edge, and an opaque inset sheet holding the copy maps to the matching target region with the layout inside it.
- A translucent shape tightly wrapping one content unit (a glow behind a product) follows that unit; tinted divider lines stay structural.
- New metrics compare backdrop coverage and empty canvas with the source, and `--strict-quality` fails a lost backdrop or a mostly empty canvas.
  On round-1 output the metric reports 24%, 16% and 38% backdrop coverage for the three held-out designs that floated a box in a blank canvas.

Painted type:
- Font sizes are integers (floor, at least 1), the size cr-renderer paints, so converter wrapping and painting agree.
- Measurement is token based and linear in words, models letter spacing per style span like cr-renderer, and is checked against the converter output.
- Text boxes hug their wrapped copy (`tight_width`, verified to keep the converter's wrapping identical), and layout uses painted bounds, so transparent art padding and empty text-box width no longer create dead space.
- The odd letter gaps (`SummerLine`, `drin k`) are renderer behavior at tiny sizes: on Linux, FreeType hinting at 7px gives Solstice Sans Bold a 1px space and 6px `u` (linear: 1.48px and 4.72px); on macOS, fractional advances are snapped to whole pixels.
  The engine cannot change hinting; it now avoids sub-8px type where the design allows.

Layout:
- Column flow (the transpose of the row DP) for wide targets: Level 2 at 1600x400 now reads badge and logo, product, then a headline column (82px, was 74px) without a dead gap.
- Splits space copy and art evenly; rows sit near their source heights (isotonic regression) with bounded gaps on extreme shapes.
- Repeated units (cards, pills) form a set laid out as an even grid; three products are one row or one column, never 2 + 1, and share one shrink factor.
- A lone unit shrinks to fit its row or column instead of blocking the shared type scale; footers use the body's type scale, so a footer can no longer outgrow the copy (held-out accented copy: one footer line instead of four).
- Score changes: headline prominence, hierarchy kept to 75% of the source ratio, steep penalty below 8px, art size including shape art, new side-by-side copy pairs and content-centroid drift; source-arrangement weight 3 to 2.

Tried and changed along the way:
- Spacing row items evenly (`space-evenly`) put large gaps between copy and art; packing them into a centred cluster reads better.
- Mapping rows to their global source heights inside split columns made banners diagonal (logo top-left, copy bottom-right); columns now use their own extent.
- Sliding art whose transparent padding crossed the canvas edge created overlaps; shrinking it about its centre does not.

Platform parity: Skia uses hinted integer advances on Linux and fractional ones on macOS, so layouts can differ between the venv and Docker even though each matches its own renderer.
Final judgments came from container renders, including an in-container run of the evaluation matrix (command in `EVALUATION.md`).

Performance: candidates measure through cached per-size tables and precomputed text keys; in the container under Rosetta the samples take 0.27s, 0.45s and 1.95s per task including rendering (round 1: 0.20s, 0.32s, 2.97s), and the slowest held-out task drops from 5.10s to 1.39s.

Verification: 56 unit tests, lint, the strict stress matrix (168 cases), fixtures (30), held-out (84) and public samples (39) with the real renderer all pass with zero gated failures; the public samples (39) and held-out (78) also pass inside the container.
Minimum font tables before and after are in `EVALUATION.md`; several minimums are lower because supporting copy no longer inflates toward the headline.

## Backend finalization on the official renderer (2026-10-30)

The renderer is back to the official starter code, so a missing asset now paints a visible labeled placeholder and contain-fit pastes with an alpha mask.
The asset tests were rewritten to pin that official behavior (warning, opaque placeholder, element retained, no crash).
No code in `pipelines/`, `scripts/` or `tests/` depends on the removed `show_missing_assets` option any more.

Missing-asset policy: the placeholder is treated as small furniture.
It stays out of content rows, keeps its ratio and the uniform canvas scale, and `pipelines/common/placeholders.py` moves it to the free spot nearest its source anchor that clears all content (shrinking to a 6px floor if needed).
Quality metrics now count it in collision checks; previously it was excluded.
At the source canvas and story sizes the placeholder used to cover the Level 3 legal line; it now sits clear of copy.

Other changes:
- `pipelines/api.py` exposes `run(source, target_canvas, pipeline=None)` for the web viewer, with a contract test.
- `scripts/run_matrix.py` uses the shared `pipelines/common/formats.py` catalogue (13 targets, adding LinkedIn banner and Pinterest pin).
- Texts sharing a row try an area-proportional width split as well as the sqrt split; medium_rect Level 3 minimum rises from 4.6px to 4.8px, at roughly 35% more search time on Level 3 (about 1.5s worst case).
- Image-only rows grow shorter art (logo beside product) up to 2x within spare width; the Level 2 728x90 logo roughly doubles in painted width with unchanged fonts.
- A narrower 0.15 image column was tried for 728x90: headline 10.2px to 11.9px, but the legal line wrapped into a 7-line corner sliver and the logo became illegible, so it was reverted.
- Rewarding headline size directly in `quality.score` (weights 0.3-1.0) barely changed selections; the limit is the candidate space, not the ranking.
- Lint (ruff with the user's global config) is clean across `pipelines/`, `scripts/` and `tests/`.

Verification: 41 tests pass.
Strict stress matrix (168 cases: variants, source canvas, schema, determinism) has zero gated failures, as do the independent fixtures with the real renderer (30 cases) and the public samples with the real renderer (39 cases).
`python -m engine.main` writes three valid JSON/PNG pairs at exact target sizes.
The minimum-font table per sample and target is in `EVALUATION.md`.
Level 3 at 728x90 remains 5.9-10.2px.

## Visual-review scoring pass (2026-10-16)

Reviewed real renders of all samples x 11 targets. Fixes in `quality.score`:
font-hierarchy preservation, secondary text/logo inflation vs the headline,
choppy-wrap penalty, canvas/headline-relative size credit caps, and a group
(pill) canvas-share penalty loosened for extreme aspect changes. `reflow`
spreads vertical slack between rows and lets lone images fill row width;
`adaptive` adds a large-image stack candidate. Results: footers/pills no longer
outgrow headlines, 1600x400 has a dominant headline and smaller pills, narrow
targets lose dead blocks. 728x90 Level 3 text remains ~6-10px. 36 tests pass;
the strict/variant matrix was not re-run after the last two scoring changes.

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
- **Proxy score** (`layout_v1._score`): our own heuristic - keeps font/image sizes close to source, penalises overlaps. **Not the official rubric** (weights unknown).
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
