# CHAMELEON — starter repo

This is the scaffolding for your engine. It handles input loading, output
writing, rendering, and Docker packaging. Resize strategies live in
**`pipelines/`**; **`engine/resize.py`** delegates to the selected strategy.
The default is `adaptive`, which searches rows, image/copy columns and image
bands, balances supporting copy against headlines, and fits group labels.
See [pipelines/README.md](pipelines/README.md) for comparisons.

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   <-- YOU IMPLEMENT THIS
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated — see `RULES.md`.

## Repo layout

```
engine/
  resize.py        <- delegates to the selected pipeline
  main.py           <- orchestrator (input -> resize() -> output). Don't need to edit this.
renderer/           <- the real renderer (transformer-convertor + cr-renderer), already vendored
pipelines/          <- registered resize strategies and shared fitting/validation
scripts/            <- comparison runner, JSON metrics and HTML previews
tests/              <- contract, layout, robustness and real-renderer regressions
brand_kit/
  assets/           <- image files referenced by asset_id in the sample designs
  fonts/            <- font files matching the schema's font_family values
input/               <- drop task JSON files here for local testing (3 samples included)
output/              <- results land here
chameleon_design_schema_v0.9.json   <- full field-by-field spec for the design format
Dockerfile
RULES.md
```

## Quick start (no Docker needed for iterating on `resize()`)

```bash
pip install -r requirements.txt
python -m engine.main
```

This processes every `*.json` file in `input/` (the 3 sample designs are
already there — one per difficulty level) and writes an `_output.json` and
`_output.png` for each into `output/`.

The `stretch` reference is a **uniform stretch** — deliberately the wrong
approach (see the main brief: "a naive program stretches the picture; a
good one moves the furniture"). It's there so the pipeline runs on day
one. Select it with `CHAMELEON_PIPELINE=stretch` to compare against the default.
Add new approaches as registered folders under `pipelines/`.

Install the evaluation dependency, run regressions and compare strategies:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m scripts.run_matrix --pipelines adaptive --schema --variants --include-source --check-determinism --strict-quality
python -m scripts.run_matrix --pipelines anchored layout_v1 flow adaptive --schema --render --reference-pipelines anchored layout_v1 flow --strict-quality
```

The comparison writes JSON outputs, per-element metrics, and an HTML report
to `output/matrix/`. `--render` adds real source/output PNGs. Use `--targets`
and `--pipelines` to narrow the sweep. Local scores are not official scores.
See [EVALUATION.md](EVALUATION.md) for release gates, independent fixtures,
visual review and the offline Docker check.

## What the self-check does (and doesn't do)

`main.py` runs a quick structural check after every task — same element
`id`s as the source, required fields present, nothing off-canvas. **This
is not the official scorer.** It exists to catch obvious mistakes before
you waste a submission on them. See `RULES.md` for what's actually
checked and graded.

A self-check warning does not fail the run — your JSON and PNG are still
written either way. Read the warning; decide whether it's a real problem
or, like the Level 2 sample's intentionally corner-bleeding decorative
circle, an expected one.

## The renderer

`main.py` calls `renderer/converter/convert.py`'s `render_design_to_png()`
(a vendored copy of `transformer-convertor`, wrapping `cr-renderer`) to
produce each task's PNG — already wired in, no setup needed. It reads
fonts/assets from `brand_kit/` and writes a real rendered preview, not a
placeholder. If you ever see plain labeled boxes instead of real text and
images in `output/*.png`, that means the import in `main.py` failed (e.g.
`cr-renderer` didn't install — check `requirements.txt` installed cleanly)
and it silently fell back to the box-and-label placeholder; don't judge
your layout quality by that fallback.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your
engine needs must be installed at **build** time (add it to
`requirements.txt`), not fetched at run time. If you're using a locally
hosted model, bake its weights into the image during the build step.

## See also

- `chameleon_design_schema_v0.9.json` — full input/output field spec
- `RULES.md` — what's checked, what's graded, and what disqualifies a submission
- FAQ — for anything not covered above
