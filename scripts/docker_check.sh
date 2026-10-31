#!/usr/bin/env bash
# One-command scoring rehearsal: build the image exactly like the judges,
# run it offline against a fresh output directory, and verify the results.
#
# Usage: scripts/docker_check.sh [--skip-build] [--no-cache] [--input DIR]
#                                [--image NAME] [--artifacts DIR]
#   --skip-build     reuse an existing image instead of rebuilding it
#   --no-cache       build from scratch (cold build; ignores the layer cache)
#   --input DIR      task directory to mount as /app/input (default: input)
#   --image NAME     image tag (default: chameleon-engine)
#   --artifacts DIR  where logs and outputs go (default: output/docker/check-<time>)
#
# Checks: build, offline run, schema, canvas and PNG size, element ids, unchanged
# type/content/font_family/asset_id, every element's unrotated x/y/width/height
# box inside the canvas (as engine/main.py self_check), engine self-check lines,
# and a second offline pass that re-renders each output with the official
# renderer in the image to surface its warnings and confirm the PNG is
# reproduced byte for byte.
# Verification needs a host Python with jsonschema and Pillow
# (.venv/bin/python is used when present; override with PYTHON=...).
# Exits non-zero if the build, the run, or any verification check fails.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="chameleon-engine"
INPUT_DIR="$ROOT/input"
BUILD=1
NO_CACHE=""
RUN_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-build) BUILD=0 ;;
    --no-cache) NO_CACHE="--no-cache" ;;
    --input|--image|--artifacts)
      if [ $# -lt 2 ]; then echo "$1 needs a value" >&2; exit 2; fi
      case "$1" in
        --input) INPUT_DIR="$(cd "$2" && pwd)" ;;
        --image) IMAGE="$2" ;;
        --artifacts) RUN_DIR="$2" ;;
      esac
      shift ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "${PYTHON:-}" ]; then
  :
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi
if ! "$PYTHON" -c "import jsonschema, PIL" 2>/dev/null; then
  echo "error: $PYTHON needs jsonschema and Pillow (pip install -r requirements-dev.txt Pillow)" >&2
  exit 2
fi

[ -n "$RUN_DIR" ] || RUN_DIR="$ROOT/output/docker/check-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
RUN_DIR="$(cd "$RUN_DIR" && pwd)"
OUT_DIR="$RUN_DIR/output"
if [ -d "$OUT_DIR" ] && [ -n "$(ls -A "$OUT_DIR")" ]; then
  echo "error: $OUT_DIR is not empty; pick a fresh --artifacts directory" >&2
  exit 2
fi
mkdir -p "$OUT_DIR"
echo "== artifacts: $RUN_DIR"

cd "$ROOT"
if [ "$BUILD" -eq 1 ]; then
  echo "== docker build --platform linux/amd64 ${NO_CACHE:+$NO_CACHE }-t $IMAGE ."
  start=$SECONDS
  # shellcheck disable=SC2086  # NO_CACHE is empty or a single flag
  if ! docker build --platform linux/amd64 $NO_CACHE -t "$IMAGE" . >"$RUN_DIR/build.log" 2>&1; then
    tail -40 "$RUN_DIR/build.log" >&2
    echo "FAIL: docker build (full log: $RUN_DIR/build.log)" >&2
    exit 1
  fi
  echo "   build: $((SECONDS - start))s"
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "FAIL: image '$IMAGE' not found (drop --skip-build to build it)" >&2
  exit 1
fi
echo "   image size: $(docker image ls "$IMAGE" --format '{{.Size}}' | head -1) on disk, $(docker image inspect "$IMAGE" --format '{{.Size}}' | awk '{printf "%.0f MB", $1 / 1000000}') content"

# Offline run, mirroring the scoring command. A named container lets a
# background poller sample memory; peak memory is approximate (polling).
NAME="chameleon-check-$$"
# shellcheck disable=SC2329  # invoked via trap
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== docker run --network none (input: ${INPUT_DIR#"$ROOT"/})"
(
  tries=0
  while ! docker inspect "$NAME" >/dev/null 2>&1; do
    tries=$((tries + 1)); [ "$tries" -gt 100 ] && exit 0; sleep 0.2
  done
  while [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; do
    # "318.5MiB / 7.7GiB" -> 318.5 (MiB)
    docker stats --no-stream --format '{{.MemUsage}}' "$NAME" 2>/dev/null | awk '{
      v = $1 + 0; u = $1; sub(/^[0-9.]+/, "", u)
      if (u == "GiB") v *= 1024; else if (u == "KiB") v /= 1024; else if (u == "B") v /= 1048576
      printf "%.1f\n", v }'
  done
) >"$RUN_DIR/mem_samples.txt" 2>/dev/null &
POLLER=$!

start=$SECONDS
set +e
docker run --name "$NAME" --network none \
  -v "$INPUT_DIR:/app/input:ro" \
  -v "$OUT_DIR:/app/output" \
  "$IMAGE" >"$RUN_DIR/stdout.txt" 2>"$RUN_DIR/stderr.txt"
RUN_STATUS=$?
set -e
RUNTIME=$((SECONDS - start))
wait "$POLLER" 2>/dev/null || true

cat "$RUN_DIR/stdout.txt"
echo "   exit status: $RUN_STATUS, wall time: ${RUNTIME}s"
PEAK_MIB="$(sort -n "$RUN_DIR/mem_samples.txt" 2>/dev/null | tail -1 || true)"
echo "   peak memory (sampled, approximate): ${PEAK_MIB:-n/a} MiB"

# Second offline pass: re-render every output JSON with the official renderer
# inside the same image. engine/main.py discards the renderer's warnings
# (missing assets, unknown element types), so this is where they surface; it
# also confirms the scored PNG is reproduced byte for byte.
echo "== renderer pass (warnings, reproducibility)"
set +e
docker run --rm --network none --entrypoint python \
  -v "$OUT_DIR:/app/output:ro" \
  "$IMAGE" -c '
import json, sys, tempfile
from pathlib import Path
from renderer.converter.convert import render_design_to_png
report, tmp = {}, Path(tempfile.mkdtemp())
for path in sorted(Path("output").glob("*_output.json")):
    name = path.name[: -len("_output.json")]
    try:
        warnings = render_design_to_png(json.loads(path.read_text()), Path("brand_kit/assets"), tmp / "r.png")
        png = path.with_name(name + "_output.png")
        same = png.is_file() and png.read_bytes() == (tmp / "r.png").read_bytes()
        report[name] = {"warnings": [str(w) for w in warnings or []], "reproduced": same}
    except Exception as exc:
        report[name] = {"error": f"{type(exc).__name__}: {exc}"}
json.dump(report, sys.stdout)
' >"$RUN_DIR/renderer_report.json" 2>"$RUN_DIR/renderer_stderr.txt"
RENDER_STATUS=$?
set -e

echo "== verify"
set +e
"$PYTHON" - "$ROOT" "$INPUT_DIR" "$OUT_DIR" "$RUN_DIR" "$RUN_STATUS" "$RENDER_STATUS" "$RUNTIME" <<'PY'
import json
import math
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image

root, input_dir, out_dir, run_dir = map(Path, sys.argv[1:5])
run_status, render_status, runtime = map(int, sys.argv[5:8])
schema = Draft202012Validator(json.loads((root / "chameleon_design_schema_v0.9.json").read_text(encoding="utf-8")))
assets = {p.name for p in (root / "brand_kit/assets").iterdir()}
failures, warnings = [], []

if run_status != 0:
    failures.append(f"container exited with status {run_status}")

# Known-benign stderr from running an amd64 image under emulation.
BENIGN = ("requested image's platform", "<jemalloc>")
for line in (run_dir / "stderr.txt").read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip() or any(b in line for b in BENIGN):
        continue
    (failures if "Traceback" in line or "Error" in line else warnings).append(f"stderr: {line}")

# engine/main.py prints "[<task>.json] OK in 1.23s -> ..." or
# "[<task>.json] N self-check warning(s) in ..." followed by "    - <problem>" lines.
engine_times, engine_problems, current = {}, {}, None
for line in (run_dir / "stdout.txt").read_text(encoding="utf-8", errors="replace").splitlines():
    m = re.match(r"\[(.+)\.json\] (.*?) in ([0-9.]+)s", line)
    if m:
        current = m.group(1)
        engine_times[current] = float(m.group(3))
        engine_problems[current] = []
    elif current and line.startswith("    - "):
        engine_problems[current].append(line[6:])

try:
    render_report = json.loads((run_dir / "renderer_report.json").read_text(encoding="utf-8"))
except ValueError:
    render_report = {}
if render_status != 0 or not isinstance(render_report, dict):
    failures.append(f"renderer pass exited with status {render_status} "
                    f"(see {run_dir / 'renderer_stderr.txt'})")
    render_report = {}

tasks = sorted(input_dir.glob("*.json"))
if not tasks:
    failures.append(f"no task files in {input_dir}")
expected = set()
for task_path in tasks:
    name = task_path.stem
    task = json.loads(task_path.read_text(encoding="utf-8"))
    source, target = task["source"], task["target_canvas"]
    tw, th = target["width"], target["height"]
    out_json, out_png = out_dir / f"{name}_output.json", out_dir / f"{name}_output.png"
    expected |= {out_json.name, out_png.name}
    problems = []
    if not out_json.is_file() or not out_png.is_file():
        failures.append(f"{name}: missing {out_json.name} or {out_png.name}")
        continue
    design = json.loads(out_json.read_text(encoding="utf-8"))
    problems += [f"schema {list(e.path)}: {e.message}" for e in schema.iter_errors(design)]
    canvas = design.get("canvas", {})
    if (canvas.get("width"), canvas.get("height")) != (tw, th):
        problems.append(f"canvas {canvas} != target {tw}x{th}")
    with Image.open(out_png) as im:
        if im.size != (tw, th):
            problems.append(f"png {im.size[0]}x{im.size[1]} != target {tw}x{th}")
    src = {el["id"]: el for el in source["elements"]}
    out_ids = [el.get("id") for el in design.get("elements", [])]
    if sorted(out_ids) != sorted(src):
        problems.append(f"element ids differ: missing {sorted(set(src) - set(out_ids))}, "
                        f"extra/duplicated {sorted(i for i in out_ids if out_ids.count(i) > 1 or i not in src)}")
    for el in design.get("elements", []):
        ref = src.get(el.get("id"))
        if ref is None:
            continue
        for key in ("type", "content", "font_family", "asset_id"):
            if ref.get(key) != el.get(key):
                problems.append(f"{el['id']}: {key} changed")
        # The unrotated x/y/width/height box must lie inside the canvas (0.5 px
        # tolerance, rotation ignored), exactly like engine/main.py self_check.
        box = [el.get(k) for k in ("x", "y", "width", "height")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box):
            problems.append(f"{el['id']}: non-numeric or non-finite geometry {box}")
        elif box[2] <= 0 or box[3] <= 0:
            problems.append(f"{el['id']}: non-positive size {box[2]}x{box[3]}")
        elif box[0] < -0.5 or box[1] < -0.5 or box[0] + box[2] > tw + 0.5 or box[1] + box[3] > th + 0.5:
            problems.append(f"{el['id']}: unrotated box x={box[0]:g} y={box[1]:g} w={box[2]:g} h={box[3]:g} "
                            f"is outside the {tw}x{th} canvas")
    if name not in engine_times:
        problems.append("no engine status line in stdout")
    problems += [f"engine self-check: {p}" for p in engine_problems.get(name, [])]
    rendered = render_report.get(name)
    if rendered is None:
        if render_report:
            problems.append("missing from the renderer pass")
    elif "error" in rendered:
        problems.append(f"renderer pass failed: {rendered['error']}")
    else:
        warnings += [f"{name}: renderer: {w}" for w in rendered["warnings"]]
        if not rendered["reproduced"]:
            warnings.append(f"{name}: re-rendering the output JSON does not reproduce the PNG byte for byte")
    # Static fallback for the most common renderer warning, in case the pass did not run.
    if not rendered:
        for el in source["elements"]:
            if el["type"] == "image" and el["asset_id"] not in assets:
                warnings.append(f"{name}: asset '{el['asset_id']}' (element '{el['id']}') is missing from "
                                "brand_kit/assets; the renderer paints a labeled placeholder box")
    status = "OK" if not problems else "FAIL"
    timing = f", resize() {engine_times[name]:.2f}s" if name in engine_times else ""
    print(f"   [{status}] {name}: {tw}x{th}, {len(out_ids)} elements{timing}")
    failures += [f"{name}: {p}" for p in problems]

extra = sorted(p.name for p in out_dir.iterdir() if p.name not in expected)
if extra:
    warnings.append(f"unexpected files in output: {extra}")
if tasks:
    engine_total = sum(engine_times.values())
    print(f"   per task: {runtime / len(tasks):.1f}s container wall time on average "
          f"({runtime}s total incl. startup), {engine_total / len(tasks):.2f}s resize() average")
for w in warnings:
    print(f"   WARNING: {w}")
for f in failures:
    print(f"   FAIL: {f}")
print(f"== {'PASS' if not failures else 'FAIL'}: {len(tasks)} task(s), {len(failures)} failure(s), {len(warnings)} warning(s)")
sys.exit(1 if failures else 0)
PY
VERIFY_STATUS=$?
set -e
exit "$VERIFY_STATUS"
