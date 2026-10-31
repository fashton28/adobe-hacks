# CHAMELEON - starter repo

This is the scaffolding for our engine, built on the hackathon starter.
It handles input loading, output writing, rendering, and Docker packaging.
Resize strategies live in **`pipelines/`**; **`engine/resize.py`** delegates to the selected strategy.
The default is `adaptive` (see [Our approach](#our-approach) and [pipelines/README.md](pipelines/README.md)).

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   <-- delegates to pipelines/ (default: adaptive)
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated - see `RULES.md`.

## Our approach

The engine treats a resize as a layout problem, not a scaling problem: it keeps every element, regroups the design into units, and searches for an arrangement that fits the target format.

- **Units.** Elements that share a `group_id` move together with one uniform transform, so groups (including rotated ones) never come apart.
  Images keep their source aspect ratios, and text keeps its content and font family; only boxes, positions and font sizes change.
- **Candidate layouts.** The default `adaptive` pipeline generates many candidate arrangements: stacks, strips, image/copy columns, vertical image bands, and multi-row layouts whose row breaks are chosen by dynamic programming.
  It also keeps the uniformly scaled `anchored` layout as an always-valid fallback.
- **Renderer-aware text fitting.** Text is measured with Skia glyph advances and the brand fonts, mirroring how the official converter wraps lines, so text fits are judged the way the PNG will actually be rendered.
  Candidates also vary how strongly font sizes follow the source hierarchy (exponents from 0.45 to 1.0); compressed hierarchies give supporting copy more room on small targets while headlines stay dominant.
- **Ranking.** Structurally invalid candidates are discarded first.
  The rest are ranked by text overflow and unrelated overlaps before softer scores such as readability, foreground image scale and closeness to the source arrangement.
- **Missing assets.** The official renderer paints a missing asset as a labeled placeholder, so `adaptive` moves such units to the free spot nearest their source anchor that clears all content.

Scores reported by our tools are local proxies from `pipelines/common/quality.py`, not official challenge scores.
The per-pipeline comparison, known limits and design notes are in [pipelines/README.md](pipelines/README.md), and the release gates are in [EVALUATION.md](EVALUATION.md).

## Repo layout

```
engine/
  resize.py        <- delegates to the selected pipeline
  main.py           <- orchestrator (input -> resize() -> output). Don't need to edit this.
renderer/           <- the real renderer (transformer-convertor + cr-renderer), already vendored
pipelines/          <- registered resize strategies (adaptive is the default), shared
                       fitting/validation/quality code in common/, and api.py for tools
scripts/
  run_matrix.py     <- comparison runner: JSON outputs, metrics, renders and an HTML report
  docker_check.sh   <- one-command offline Docker scoring rehearsal with verification
tests/              <- contract, layout, robustness and real-renderer regressions
  fixtures/         <- independent fixture tasks
  heldout/          <- held-out tasks, never used for tuning (see its README)
  heldout2/         <- a second, blind held-out corpus (see its README)
webapp/             <- local web viewer for the engine (dev/demo tool, not in the Docker image)
express-addon/      <- Adobe Express add-on panel, a thin client of the web viewer's API
brand_kit/
  assets/           <- image files referenced by asset_id in the sample designs
  fonts/            <- font files matching the schema's font_family values
input/               <- drop task JSON files here for local testing (3 samples included)
output/              <- results land here
chameleon_design_schema_v0.9.json   <- full field-by-field spec for the design format
Dockerfile
RULES.md
```

## Setup

The project uses Python 3.11 (the version in the Docker image).
With [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt
```

Or with the standard library's `venv`:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` holds the runtime dependencies (the renderer stack); `requirements-dev.txt` adds `jsonschema` for evaluation.
The commands below use `.venv/bin/python`; with the environment activated, plain `python` works too.

## Quick start (no Docker needed for iterating on `resize()`)

```bash
.venv/bin/python -m engine.main
```

This processes every `*.json` file in `input/` (the 3 sample designs are already there - one per difficulty level) and writes an `_output.json` and `_output.png` for each into `output/`.

Pick another pipeline with the `CHAMELEON_PIPELINE` environment variable:

```bash
CHAMELEON_PIPELINE=anchored .venv/bin/python -m engine.main
```

The `stretch` reference is a **uniform stretch** - deliberately the wrong approach (see the main brief: "a naive program stretches the picture; a good one moves the furniture").
It is kept as a benchmark; select it with `CHAMELEON_PIPELINE=stretch` to compare against the default.
New approaches are added as registered folders under `pipelines/` (see [pipelines/README.md](pipelines/README.md)).

## Tests and comparisons

```bash
.venv/bin/python -m unittest discover -s tests -v                       # engine regressions
.venv/bin/python -m unittest discover -s webapp/tests -t . -v           # web viewer API
.venv/bin/python -m scripts.run_matrix --pipelines adaptive --schema --variants --include-source --check-determinism --strict-quality
.venv/bin/python -m scripts.run_matrix --pipelines anchored layout_v1 flow adaptive --schema --render --reference-pipelines anchored layout_v1 flow --strict-quality
```

The comparison writes JSON outputs, per-element metrics, and an HTML report to `output/matrix/`.
`--render` adds real source/output PNGs.
Use `--targets` and `--pipelines` to narrow the sweep.
Local scores are not official scores.
See [EVALUATION.md](EVALUATION.md) for release gates, independent fixtures, visual review and the offline Docker check.

## What the self-check does (and doesn't do)

`main.py` runs a quick structural check after every task - same element `id`s as the source, required fields present, nothing off-canvas.
**This is not the official scorer.**
It exists to catch obvious mistakes before you waste a submission on them.
See `RULES.md` for what's actually checked and graded.

A self-check warning does not fail the run - your JSON and PNG are still written either way.
Read the warning; decide whether it's a real problem or, like the Level 2 sample's intentionally corner-bleeding decorative circle, an expected one.

## The renderer

`main.py` calls `renderer/converter/convert.py`'s `render_design_to_png()` (a vendored copy of `transformer-convertor`, wrapping `cr-renderer`) to produce each task's PNG - already wired in, no setup needed.
It reads fonts/assets from `brand_kit/` and writes a real rendered preview, not a placeholder.
If you ever see plain labeled boxes instead of real text and images in `output/*.png`, that means the import in `main.py` failed (e.g. `cr-renderer` didn't install - check `requirements.txt` installed cleanly) and it silently fell back to the box-and-label placeholder; don't judge your layout quality by that fallback.
The renderer in this repository is the official starter renderer, unmodified.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your engine needs must be installed at **build** time (add it to `requirements.txt`), not fetched at run time.
If you're using a locally hosted model, bake its weights into the image during the build step.

To rehearse this in one command, run:

```bash
scripts/docker_check.sh                      # build, run offline on input/, verify
scripts/docker_check.sh --skip-build         # reuse the existing image
scripts/docker_check.sh --input tests/heldout2
```

It builds the image for `linux/amd64`, runs it with `--network none` against a fresh output directory, and verifies the results: exit status, unexpected stderr, schema validity, canvas and PNG sizes, element ids, and unchanged `type`, `content`, `font_family` and `asset_id`.
Artifacts and logs go to `output/docker/check-<timestamp>/`, and the script exits non-zero if any step fails.
Verification runs on the host and needs `jsonschema` and Pillow (the `.venv` from [Setup](#setup) has both).

## Web viewer

A local viewer runs the engine and the official renderer behind a small HTTP API:

```bash
.venv/bin/python -m webapp
```

Open http://localhost:8765, pick a sample (challenge samples, fixtures and held-out tasks are listed) or drop a task JSON, choose a target format and pipeline, and compare the rendered source and output with validation and quality diagnostics.
"Compare all formats" renders the design in every catalogue format side by side.
Options, the API and tests are documented in [webapp/README.md](webapp/README.md).
The viewer is a development and demo tool; it is not part of the Docker image.

## Adobe Express add-on

`express-addon/` is an Adobe Express panel that sends a design to the web viewer's API, shows the result, and inserts the rendered PNG into the current Express page.
It needs the web viewer running locally.
Build, test and loading steps are in [express-addon/README.md](express-addon/README.md).

## See also

- `chameleon_design_schema_v0.9.json` - full input/output field spec
- `RULES.md` - what's checked, what's graded, and what disqualifies a submission
- `FAQ.md` - for anything not covered above
- [pipelines/README.md](pipelines/README.md) - pipeline comparison and known limits
- [EVALUATION.md](EVALUATION.md) - release gates and the offline Docker check
