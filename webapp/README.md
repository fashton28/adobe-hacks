# CHAMELEON viewer

A local web viewer for the resize engine.
Load a design, choose a target format, run a pipeline, and compare source and output as rendered by the official renderer, with validation and quality diagnostics.
It is a development and demo tool; it is not part of the Docker scoring image.

## Run

From the repository root:

```
.venv/bin/python -m webapp
```

Open the printed URL (default http://localhost:8765).
By default the server listens on both loopback addresses, `127.0.0.1` and `::1`, so `localhost` works whichever address your browser resolves it to; on a machine without IPv6 loopback it uses `127.0.0.1` alone.
Options: `--port 9000` (use `0` for any free port), `--host <address>` to bind exactly one address (for example `127.0.0.1`, or `0.0.0.0` / `::` to expose it on the network), `--quiet` to silence the request log.
The startup line also names the default pipeline.
There are no extra dependencies: the backend is the Python standard library plus the repository's own `pipelines/` and `renderer/` packages, and the front end is static HTML, CSS and JavaScript.

## Using it

1. Pick a sample (challenge samples, test fixtures and every `tests/heldout*` corpus are grouped) or drop a task JSON onto the upload box.
   A bare design `{canvas, elements}` is accepted too.
2. Choose a target format.
   "Task target" is the task's own `target_canvas`; the others come from `pipelines/common/formats.py`; "Custom" takes any size up to 8192 px.
3. Choose a pipeline and press Run (or Ctrl/Cmd + Enter).
   Picking a sample or a format runs immediately.

The result view shows the validation badge, side-by-side previews (click either to open a Fit / 100% / 200% zoom view), an element-box overlay with ids, quality metrics, renderer warnings and a per-element table.
Hovering a table row highlights that element in both previews.
Download buttons save the output JSON and PNG.
"Compare all formats" runs the design against every catalogue format in sequence and shows a grid of results; click a card to inspect it.
"Stop" cancels the run, including the request in flight, and loading another design during a run stops it too.

## HTTP API

All responses are JSON and carry `Access-Control-Allow-Origin: *`; `OPTIONS` preflights return 204.

| Method | Path | Response |
| --- | --- | --- |
| GET | `/api/health` | `{"ok": true}` |
| GET | `/api/formats` | `{"formats": [{key, label, width, height}, ...]}` |
| GET | `/api/pipelines` | `{"pipelines": [names], "default": name}` |
| GET | `/api/samples` | `{"samples": [{name, dir, task_id, difficulty_label, canvas, target_canvas, element_count}]}` |
| GET | `/api/samples/<dir>/<name>` | the raw task JSON (`dir` is `input`, `fixtures`, or a held-out folder such as `heldout` or `heldout2`) |
| POST | `/api/resize` | see below |

`/api/pipelines` reports as `default` the pipeline a request without `pipeline` will use: the `CHAMELEON_PIPELINE` environment variable when it names a known pipeline (the same variable the engine CLI reads), otherwise `pipelines.DEFAULT`.
An unknown `CHAMELEON_PIPELINE` value is ignored with a warning at startup.

`POST /api/resize` accepts `{"source": design, "target_canvas": {"width", "height"}, "pipeline": optional}` or `{"task": full_task_json, "pipeline": optional}`.
It returns `{output, validation, metrics, score, pipeline, elapsed_ms, warnings, source_png, output_png}`, where the PNGs are `data:image/png;base64,...` URLs rendered at native canvas size and `pipeline` is the pipeline that actually ran.
Invalid input returns 400 with `{"error": message}`; an engine or renderer failure returns 500 with `{"error": message}` and the server keeps running.
Bodies must carry a `Content-Length` of at most 16 MiB (413 otherwise); chunked bodies are rejected with 400, and canvases are limited to 8192 px per side.

Brand assets and fonts are served read-only at `/assets/<file>` and `/fonts/<file>`.

Engine work and rendering are serialized with a lock, so concurrent requests queue rather than race.
Connections that stay idle or stall mid-request for 30 seconds are closed, so they cannot hold server threads.
Static files, assets and fonts are resolved inside their folders only: path traversal, hidden files and symlinks that leave the folder return 404.
Every response allows any origin (the Express add-on calls it from another origin), which also lets any web page you visit call your local server; it is read-only and serves only the repository's samples and brand files, but do not expose it on a network you do not trust.
The engine is called through `pipelines.api.run`; if that module is missing the server falls back to `pipelines.get_pipeline` plus the shared validation and quality helpers.

## Tests

```
.venv/bin/python -m unittest discover -s webapp/tests -t . -v
```

The tests start the server on an ephemeral port and exercise every endpoint, including a real resize of the level-1 sample, CORS preflight, bad input, request framing, the advertised default pipeline, binding `localhost` on both IPv4 and IPv6, and a simulated engine failure.

## Notes

- Scores and metrics are local proxies from `pipelines/common/quality.py`, not official challenge scores.
- A missing asset (for example in the level-3 sample) is painted by the renderer as a labeled placeholder and listed under renderer warnings.
- Temporary render files are written to `output/webapp/render-tmp/` and deleted immediately after each render.
