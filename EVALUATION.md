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
python -m scripts.run_matrix --pipelines adaptive --schema --variants --include-source --check-determinism --strict-quality --output-dir output/backend/stress
python -m scripts.run_matrix --input-dir tests/fixtures --pipelines adaptive --schema --render --strict-quality --check-determinism --include-source --output-dir output/backend/fixtures
python -m scripts.run_matrix --pipelines adaptive --schema --render --strict-quality --check-determinism --output-dir output/backend/render
python -m scripts.run_matrix --pipelines anchored layout_v1 flow adaptive --schema --render --strict-quality --reference-pipelines anchored layout_v1 flow --output-dir output/backend/comparison
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
   Overlaps inside a group and behind translucent decorations are intentional
   candidates. The rectangle metric is conservative for transparent artwork.
4. **Readability:** report every text size, counts below 6px and 10px, and the
   minimum per design. Use `--min-font 10` for a feasible readable subset;
   use the stress suite to measure compromises. These thresholds are diagnostic,
   not official rules. Passing the overflow gate does not imply readable text.
5. **Stability:** repeated calls, renamed ids/groups, reordered elements with
   distinct geometry, and intervening tasks must produce stable geometry.
   Test source array reordering only where paint order is unambiguous. Tests
   also check font metrics against the real converter and long unbroken words.
6. **Visual review:** inspect native-size source/output comparisons for all
   public tasks and representative portrait, landscape and narrow targets.
   Check complete visible copy, headline prominence, product/logo visibility,
   coherent buttons/badges, margins and contrast. Record failures even when the
   proxy score improves. A 6px label can fit mathematically and still be too small.
   Inspect lettering baked into images too: JSON font metrics cannot detect it.
   `metrics.images` reports visible artwork dimensions after transparent padding
   and image fitting, making product/logo shrinkage easier to spot.

## Current results (2026-10-30)

All 41 unit tests pass (`python -m unittest discover -s tests -v`).
Gated runs, adaptive pipeline, all with zero gated failures:

| Run | Cases | Contract | Overflow | Overlap | Nondeterministic | Below 6px | Median ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Public + variants + source canvas (`stress`) | 168 | 0 | 0 | 0 | 0 | 41 | 122 | 1781 |
| Independent fixtures, real renderer | 30 | 0 | 0 | 0 | 0 | 0 | 53 | 127 |
| Public samples, real renderer | 39 | 0 | 0 | 0 | 0 | 6 | 126 | 2099 |

Minimum font size (px) per public sample and target, real renderer run:

| Target | Size | Level 1 | Level 2 | Level 3 |
| --- | --- | ---: | ---: | ---: |
| instagram_post | 1080x1080 | 30.0 | 26.8 | 16.5 |
| instagram_portrait | 1080x1350 | 54.9 | 33.5 | 12.0 |
| story | 1080x1920 | 68.0 | 37.9 | 20.4 |
| youtube_thumb | 1280x720 | 45.3 | 25.3 | 16.2 |
| facebook_cover | 1640x624 | 58.1 | 32.4 | 19.5 |
| twitter_header | 1500x500 | 53.1 | 29.6 | 17.3 |
| linkedin_banner | 1584x396 | 56.1 | 27.9 | 16.4 |
| pinterest_pin | 1000x1500 | 53.1 | 37.2 | 20.1 |
| banner_wide | 1600x400 | 56.6 | 28.2 | 16.6 |
| leaderboard | 728x90 | 25.8 | 10.5 | 5.9 |
| skyscraper | 160x600 | 21.2 | 7.0 | 5.4 |
| medium_rect | 300x250 | 10.8 | 7.2 | 4.8 |
| a4_portrait | 794x1123 | 39.8 | 27.8 | 15.2 |

The requested targets are Level 1 at 1080x1350, Level 2 at 1600x400 and Level 3 at 728x90.
Level 3 at 728x90 keeps all copy at 5.9-10.2px (headline 10.2px, legal line 5.9px).
Its binding constraint is the row of four pills: their source widths total 1310px and one shared scale drives every font, so even an empty canvas would cap pill labels near 8.3px.
Level 3 at instagram_portrait reports 12px because the source legal line is 12px.

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
needed. The container check is owned by the Docker track and was not re-run as part of the backend pass.
RULES.md sets no hard latency limit; quality is prioritized over speed.
