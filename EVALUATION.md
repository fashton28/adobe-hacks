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
python -m scripts.run_matrix --pipelines adaptive --schema --variants --include-source --check-determinism --strict-quality --output-dir output/eval-public
python -m scripts.run_matrix --input-dir tests/fixtures --pipelines adaptive --schema --render --strict-quality --output-dir output/eval-independent
python -m scripts.run_matrix --pipelines anchored layout_v1 flow adaptive --schema --render --strict-quality --reference-pipelines anchored layout_v1 flow --output-dir output/eval-comparison
```

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
Absent assets remain in the JSON and warnings but paint transparently in the
preview. Use `show_missing_assets=True` with `render_design_to_png()` for diagnostic
placeholders. Missing artwork does not consume adaptive content rows or count
as a visible collision. Mixed groups retain their shared transform.

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

## Corpus and independence

- `input/`: the three unchanged public samples, across eleven development
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
needed. Docker is unavailable in the current development environment, so the
container check remains unverified. No official latency/memory limit is assumed.
