# AGENT.md — guide for humans and AI agents working in this repo

CHAMELEON (Adobe Hackathon 2026): given a source design JSON and a target canvas, output the same elements
repositioned/resized to fit. Read `README.md`, `RULES.md`, `FAQ.md`, and `chameleon_design_schema_v0.9.json` first.

## Layout
- `engine/` — starter plumbing (`main.py` orchestrator; `resize.py` just delegates to a pipeline). Avoid editing `main.py`.
- `pipelines/` — all our approaches, one folder each (see `pipelines/README.md`). **Work goes here.**
- `renderer/`, `brand_kit/`, `input/`, schema, `Dockerfile` — given; change only when necessary (Dockerfile must `COPY` any new top-level code dir).
- `GPT-plan.md` — long-range plan; `pipelines/README.md` records how we deviate from it.
- `output/` — generated, git-ignored.

## Commands (run from repo root; use Python 3.11 to match Docker, e.g. `uv venv --python 3.11 .venv311`)
```
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # PowerShell: .\.venv\Scripts\pip ...
python -m engine.main                       # runs every input/*.json -> output/
python -m scripts.run_matrix [--render]    # every sample x 11 common target sizes x every pipeline, validated + scored
CHAMELEON_PIPELINE=<name> python -m engine.main
```
Always look at `output/*_output.png` (real renderer, not the box fallback — if you see labeled boxes, the renderer import failed).

## Hard rules (from RULES.md)
- Same element ids, same count; nothing added/removed.
- Never regenerate/redraw/replace asset pixels (disqualifying). Don't add the intentionally missing holiday badge asset.
- Don't change `content` or `font_family`; `font_size`, position, size may change.
- Foreground images keep aspect ratio (~5%); full-bleed `cover` backgrounds may crop. Nothing off-canvas.
- Offline at runtime: install everything at Docker build time; any fine-tuned model weights must be public.

## Conventions
- **No absolute paths** anywhere (code, docs, configs). Resolve from `Path(__file__)` or the repo-root working directory, as `engine/main.py` does.
- Each pipeline: `pipelines/<name>/pipeline.py` with `resize(source, target_canvas)`; register in `pipelines/__init__.py`; share code via `pipelines/common/`.
- Never mutate the input `source`; deep-copy.
- Deterministic output (no randomness, no wall-clock-dependent search).
- Keep generated files, `.venv/`, and local scratch out of git.
- Shared repo: small focused commits, don't rewrite others' pipeline folders; add a new folder instead.
