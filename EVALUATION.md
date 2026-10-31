# Evaluation

CHAMELEON transforms design geometry while retaining every element, its copy,
fonts, assets, styles and group relationships. JSON validity and rendered
readability are separate requirements. The official rubric is not available;
the local score is a development proxy, not a predicted competition grade.

## Run

Use Python 3.11, matching Docker. Install production dependencies from
`requirements.txt` and evaluation dependencies from `requirements-dev.txt`.
From the repository root:

```text
python -m unittest discover -s tests -v
python -m scripts.run_matrix --pipelines adaptive --schema --variants --include-source --check-determinism --strict-quality --output-dir output/engine/stress
python -m scripts.run_matrix --input-dir tests/fixtures --pipelines adaptive --schema --render --strict-quality --check-determinism --include-source --output-dir output/engine/fixtures
python -m scripts.run_matrix --input-dir tests/heldout --pipelines adaptive --schema --render --strict-quality --check-determinism --include-source --output-dir output/engine/heldout
python -m scripts.run_matrix --pipelines adaptive --schema --render --strict-quality --check-determinism --output-dir output/engine/input
python -m scripts.run_matrix --pipelines anchored layout_v1 flow adaptive --schema --render --strict-quality --reference-pipelines anchored layout_v1 flow --output-dir output/engine/comparison
scripts/docker_check.sh                        # also: --input tests/heldout, --input tests/fixtures
```

Targets come from the shared catalogue in `pipelines/common/formats.py`
(`TARGETS`), which the web viewer also uses.
The runner always adds a task's requested target when it is absent from the
selected catalogue. `--targets leaderboard banner_wide instagram_portrait`
narrows development runs. Reference pipelines remain in the report but do not
gate the exit status. By default only `stretch` is a reference; specify every
other reference explicitly when comparing known weaker approaches.

Open the generated `index.html` to compare source and output PNGs. Click a
preview for native resolution. `report.json` includes per-element overflow,
font sizes, visible image bounds, missing assets, overlap pairs, timing, contract/schema errors, search decisions,
package versions, code hashes and input hashes. `summary` reports worst and median minimum
font sizes, failures, tiny-copy counts and median/p95 runtime per pipeline.
The source/output JSONs are saved alongside it. `--render` calls the actual
renderer directly and fails on renderer errors; it never accepts box previews.
Render dimensions are checked without the renderer's usual 2048px cap.
The renderer is the official, unmodified starter renderer that judges use.
It paints an absent asset as a visible, opaque, labeled grey placeholder box and emits a warning; the element is never dropped.
Contain fitting pastes RGBA art using its own alpha as the mask, so semi-transparent edges are slightly attenuated; `tests/test_assets.py` pins both behaviors.

### Missing-asset policy

Because the placeholder is visible in the scored PNG, a fully missing image unit is treated as small furniture rather than content (`pipelines/common/placeholders.py`):

- it keeps its id, `asset_id` and aspect ratio, stays on-canvas and never takes space in content rows;
- its size is its source size times the uniform canvas scale `min(W/Ws, H/Hs)`, so it shrinks on tiny targets;
- it moves, as one rigid unit, to the free spot nearest its source anchor that clears every content unit by a small gap, trading drift against shrinking (down to a 6px floor);
- if no free spot exists, the least-overlapping spot is used and the overlap is reported.

`quality.metrics` counts missing units in collision checks (so `--strict-quality` fails if a placeholder covers copy) but excludes them from the source-arrangement shift.
Mixed groups (some art present) keep their shared group transform.

## Acceptance

1. **Contract:** zero schema/identity/property/bounds/ratio/group-transform
   failures; no input mutation. All sizes must be finite. Assets and copy must
   remain unchanged, including the deliberately missing holiday badge.
2. **Complete copy:** zero measured text overflow on feasible designs. Groups
   retain their geometry transform; labels may reduce font size to fit. The
   actual renderer must produce the expected dimensions and retain its warnings.
3. **Collision:** zero unrelated content-unit overlaps on this corpus.
   Overlaps inside a group and behind translucent decorations are intentional candidates.
   Collisions use painted bounds: transparent padding of art and empty text-box space do not count.
4. **Canvas fill:** a full-bleed backdrop in the source (any unrotated element covering at least 85% of it: solid fill, paper sheet, scrim or cover image) must still cover the target as far as it can, within 5%.
   Shapes and cover images can reach the whole canvas; other images reach their ratio-preserving fit.
   The empty canvas share may not grow by more than 40 points over the source.
   `--strict-quality` fails either, which catches a backdrop shrunk into a floating box that overflow and collision checks cannot see.
5. **Readability:** report every text size, counts below 6px and 10px, and the
   minimum per design. Use `--min-font 10` for a feasible readable subset;
   use the stress suite to measure compromises. These thresholds are diagnostic,
   not official rules. Passing the overflow gate does not imply readable text.
6. **Stability:** repeated calls, renamed ids/groups, reordered elements with
   distinct geometry, and intervening tasks must produce stable geometry.
   Test source array reordering only where paint order is unambiguous. Tests
   also check font metrics against the real converter and long unbroken words.
7. **Visual review:** inspect native-size source/output comparisons for all
   public tasks and representative portrait, landscape and narrow targets.
   Check complete visible copy, headline prominence, product/logo visibility,
   coherent buttons/badges, margins and contrast. Record failures even when the
   proxy score improves. A 6px label can fit mathematically and still be too small.
   Inspect lettering baked into images too: JSON font metrics cannot detect it.
   `metrics.images` reports visible artwork dimensions after transparent padding
   and image fitting, making product/logo shrinkage easier to spot.

## Current results (2026-10-31, round 4)

All 73 unit tests pass (`python -m unittest discover -s tests`), including the new `tests/test_fidelity.py` and the renderer-backed robustness tests.
Lint is clean (`uvx ruff check pipelines scripts tests --extend-exclude tests/heldout3/generate.py`).
Gated runs on the macOS venv, adaptive pipeline, with zero gated failures under `--strict-quality`: the stress matrix (168 cases, schema, variants, source canvas, determinism) and rendered runs with schema, determinism and source canvas on `input/` (39), `tests/fixtures` (30), `tests/heldout` (84), `tests/heldout2` (112) and `tests/heldout3` (112).
`scripts/docker_check.sh --image chameleon-engine4` passes on `input/`, `tests/fixtures`, `tests/heldout`, `tests/heldout2` and `tests/heldout3`; the slowest task takes 2.4s in the container (Level 3).

Every matrix row now reports `fidelity_violations` (column `fid`) and the details from `pipelines/common/fidelity.py`: occluded, contrast, camouflaged, indistinct and escaped relationships, plus soft `separated` stacks.
The adaptive ranking treats the violation count as a hard tier; at the requested targets every task in all five corpora selects a layout with zero violations (round-3 outputs had 3 on heldout3_02, 2 on heldout3_05, 3 on heldout3_07, 1 on heldout3_08 and 2 on heldout_04).
Across all development targets, two cases keep one violation because no candidate satisfies every relationship.
Fidelity is not a `--strict-quality` gate, for that reason.

A fuzz loop over random designs (rotated groups, missing assets, text only, tiny and huge canvases, bleeding elements, zero sizes) must validate and render with the official renderer; a small deterministic version runs in `tests/test_robustness.py`.

## Current results (2026-10-31, round 3)

All unit tests pass (`python -m unittest discover -s tests`), including the new `tests/test_robustness.py`.
Lint is clean (`uvx ruff check pipelines scripts tests`, with `--extend-exclude tests/heldout3` while that blind set is being authored).
Gated runs on the macOS venv, adaptive pipeline, all with zero gated failures under `--strict-quality`:
the stress matrix (public samples, variants, source canvas, schema, determinism), and rendered runs with schema, determinism and source canvas on `input/`, `tests/fixtures`, `tests/heldout` and `tests/heldout2`.
`scripts/docker_check.sh` passes on `input/`, `tests/fixtures`, `tests/heldout` and `tests/heldout2` (every task at most 2.3s in the container).
`--task-only` limits a run to each task's requested target, which is the quickest visual loop.

Every matrix row now also reports the round-3 composition measurements from `quality.composition`: margin violations, containment violations, artwork outside its prominence band, artwork drifting from the headline scale, oversized components, slack split unlike the source, decoration slivers and text at or below 7px.
They feed the ranking but are not gates, because the anchored fallback cannot always satisfy them.
Round-3 rules, container results per task and remaining weaknesses are recorded in `tested-strats.md` (2026-10-31).

## Results (2026-10-30, round 2)

All 56 unit tests pass (`python -m unittest discover -s tests -v`).
Lint is clean (`uvx ruff check pipelines scripts tests`).
Gated runs, adaptive pipeline, all with zero gated failures (strict quality includes the canvas-fill gate):

| Run | Cases | Contract | Overflow | Overlap | Backdrop / empty | Nondeterministic |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Public + variants + source canvas (`stress`, macOS venv) | 168 | 0 | 0 | 0 | 0 | 0 |
| Independent fixtures, real renderer, source canvas (macOS venv) | 30 | 0 | 0 | 0 | 0 | 0 |
| Held-out corpus, real renderer, source canvas (macOS venv) | 84 | 0 | 0 | 0 | 0 | 0 |
| Public samples, real renderer (macOS venv) | 39 | 0 | 0 | 0 | 0 | 0 |
| Public samples, real renderer, inside the Linux container | 39 | 0 | 0 | 0 | 0 | not run |
| Held-out corpus, real renderer, inside the Linux container | 78 | 0 | 0 | 0 | 0 | not run |

Minimum painted font size (px) per public sample and target.
"Before" is round 1 (commit `0fe5c64`), whose fractional sizes paint at the integer in brackets.
"venv" is macOS; "Docker" is the same matrix run inside the scored image, where Skia's hinted metrics can change the selected layout.

| Target | L1 before | L1 venv | L1 Docker | L2 before | L2 venv | L2 Docker | L3 before | L3 venv | L3 Docker |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| instagram_post | 30.0 (30) | 38 | 38 | 26.8 (26) | 18 | 18 | 16.5 (16) | 14 | 14 |
| instagram_portrait | 54.9 (54) | 38 | 38 | 33.5 (33) | 26 | 26 | 12.0 (12) | 12 | 12 |
| story | 68.0 (67) | 59 | 59 | 37.9 (37) | 37 | 37 | 20.4 (20) | 19 | 26 |
| youtube_thumb | 45.3 (45) | 39 | 39 | 25.3 (25) | 25 | 25 | 16.2 (16) | 15 | 15 |
| facebook_cover | 58.1 (58) | 50 | 50 | 32.4 (32) | 32 | 32 | 19.5 (19) | 15 | 15 |
| twitter_header | 53.1 (53) | 46 | 46 | 29.6 (29) | 29 | 29 | 17.3 (17) | 15 | 15 |
| linkedin_banner | 56.1 (56) | 48 | 48 | 27.9 (27) | 26 | 26 | 16.4 (16) | 13 | 13 |
| pinterest_pin | 53.1 (53) | 53 | 53 | 37.2 (37) | 29 | 29 | 20.1 (20) | 15 | 15 |
| banner_wide | 56.6 (56) | 49 | 49 | 28.2 (28) | 26 | 26 | 16.6 (16) | 13 | 13 |
| leaderboard | 25.8 (25) | 22 | 22 | 10.5 (10) | 10 | 10 | 5.9 (5) | 5 | 4 |
| skyscraper | 21.2 (21) | 18 | 18 | 7.0 (6) | 7 | 7 | 5.4 (5) | 6 | 6 |
| medium_rect | 10.8 (10) | 10 | 10 | 7.2 (7) | 7 | 7 | 4.8 (4) | 5 | 5 |
| a4_portrait | 39.8 (39) | 39 | 39 | 27.8 (27) | 22 | 22 | 15.2 (15) | 15 | 15 |

Lower minimums are mostly deliberate: round 1 inflated supporting copy toward the headline (Level 1 at 1080x1350 painted the CTA at 54px under a 75px headline; it is now 38px under 76px, the source's 1:2 ratio), and the score now credits headline prominence and art size.
The minimum alone is therefore not a quality ranking; inspect the PNGs.
Level 3 at 728x90 in the container paints the headline at 13px (11px before) and the legal line at 4px (5px before); everything is inside the canvas (round 1 cut the legal line at the bottom edge).

Held-out corpus at its requested targets, container renders, minimum painted font before and after: product trio 27 to 31 (no 2 + 1 restack), sparse decor 7 to 30 (backdrop now covers the canvas, previously 24%), accented copy 31 to 26 (footer one line instead of four), editorial columns 8 to 19 (paper sheet now covers the canvas, previously 16%), layered groups 15 to 25 (scrim covers the canvas, previously 38%), severe downscale 7 to 7.

Container runtime per task (`python -m engine.main` inside the image under Rosetta, including rendering): Level 1 0.27s, Level 2 0.45s, Level 3 1.95s; held-out 0.18s to 1.39s.
Round 1 measured 0.20s, 0.32s and 2.97s for the samples and up to 5.10s (editorial columns) in the same setup.
Inside the in-container matrix, search time per case has a median of 0.31s and a maximum of 2.1s (Level 3 at wide banner sizes).

## Corpus and independence

- `input/`: the three unchanged public samples, across the thirteen catalogue
  formats, their original canvases and actual requested targets.
- `--variants`: identifier renaming/no notes, longer ungrouped copy, and
  rotated groups. These expose brittle logic but are not independent designs.
- `tests/fixtures/`: two independently arranged development designs. One has
  asymmetric product/copy regions and mixed style runs; the other has no
  foreground images, a rotated label group and an unbreakable word. Their
  actual requested sizes are included even though absent from the catalogue.
- **Held-out evaluation:** freeze additional independently authored task JSONs
  in a separate directory before tuning weights or adding patterns. Run the
  same runner via `--input-dir`. Do not claim the included development fixtures
  as held-out evidence; they were used during implementation.
- `tests/heldout/` was authored blind, but round 2 fixed failure classes it exposed (lost backdrops, uneven restacks, oversized footers), so it is now development data rather than held-out evidence.
  A new blind set is being authored separately; the engine track did not open it.

More useful next fixtures: three or more image groups, coincident geometry,
unusually long group labels, supported non-ASCII text, sparse decoration-only
designs, and severe downscaling. Mark impossible readability goals as stress
cases while retaining all structural gates. Do not shorten copy to pass them.

## Offline integration

Run `python -m engine.main` and inspect the three JSON/PNG pairs. Then build
and run the container against a fresh output directory:

```powershell
docker build --platform linux/amd64 -t chameleon-engine .
$evalInput = Join-Path (Get-Location).Path 'input'
$evalOutput = Join-Path (Get-Location).Path 'output/container-eval'
New-Item -ItemType Directory -Force $evalOutput
docker run --rm --network none --mount "type=bind,source=$evalInput,target=/app/input,readonly" --mount "type=bind,source=$evalOutput,target=/app/output" chameleon-engine
```

Use a new output folder each run so stale files cannot satisfy the check.
Verify one artifact pair per task, target dimensions, contract/schema validity
and actual text/asset rendering. No runtime network access or downloads are
needed. `scripts/docker_check.sh` does all of this in one command.
RULES.md sets no hard latency limit; quality is prioritized over speed.

### Platform parity

Skia returns hinted integer glyph advances on Linux and fractional ones on macOS.
The engine measures exactly like the renderer on the same host, so copy never overflows on either platform, but the selected layout can differ between the venv and the container.
Make final visual judgments from container renders.
To run the evaluation matrix inside the scored image, mount the repository:

```text
docker run --rm --platform linux/amd64 --network none --entrypoint python -v "$PWD:/work" -w /work chameleon-engine -m scripts.run_matrix --pipelines adaptive --render --strict-quality --output-dir output/engine/docker-matrix-input
```

`--schema` needs `requirements-dev.txt`, which the image does not install.
