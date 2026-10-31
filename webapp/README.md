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
Options: `--port 9000` (use `0` for any free port), `--host <address>` to bind exactly one address (for example `127.0.0.1`, or `0.0.0.0` / `::` to expose it on the network), `--allow-origin <pattern>` to let another web origin call the API (see Security below), `--quiet` to silence the request log.
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

All API responses are JSON.
Cross-origin browser access is limited to the origins listed under Security below; for those, responses echo the caller in `Access-Control-Allow-Origin` and `OPTIONS` preflights return 204.

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
Bodies must be sent with `Content-Type: application/json` (415 otherwise) and a `Content-Length` of at most 16 MiB (413 otherwise); chunked bodies are rejected with 400, canvases are limited to 8192 px per side and designs to 500 elements (400 otherwise).

Brand assets and fonts are served read-only at `/assets/<file>` and `/fonts/<file>`.

Engine work and rendering are serialized with a lock, so concurrent requests queue rather than race.
Connections that stay idle or stall mid-request for 30 seconds are closed, so they cannot hold server threads.
Static files, assets and fonts are resolved inside their folders only: path traversal, hidden files and symlinks that leave the folder return 404.
The engine is called through `pipelines.api.run`; if that module is missing the server falls back to `pipelines.get_pipeline` plus the shared validation and quality helpers.

## Security

The server runs on your machine, and any web page you visit can try to reach it, so it applies these checks before doing any work.

- **Host header.**
  When bound to loopback (the default, or `--host 127.0.0.1` / `::1`), only `localhost`, `127.0.0.1` and `[::1]` with the bound port are accepted; anything else gets 403.
  This defeats DNS rebinding, where a foreign domain is made to resolve to 127.0.0.1.
  If you bind another address with `--host`, any Host is accepted because the server cannot know the names you will use.
  A request without a Host header gets 400.
- **Origin.**
  A request that carries an `Origin` header is answered only when the origin is the server itself, a loopback origin on any port over http or https (including the add-on dev server at `https://localhost:5241`), `https://*.adobe.com` (Adobe Express) or `https://*.adobe-addons.com` (published add-on panels such as `https://<id>.wxp.adobe-addons.com`).
  Other origins, including the opaque `null` origin of sandboxed frames and `file://` pages, get 403 and no CORS headers.
  Add more with `--allow-origin https://example.com` or `--allow-origin 'https://*.example.com'` (repeatable, a port may be given); `--allow-origin '*'` restores the old allow-everything behaviour.
  Allowed origins are echoed in `Access-Control-Allow-Origin` with `Vary: Origin`, and Chrome's Private Network Access preflight header is answered for them.
  Requests without `Origin` (curl, scripts, page navigation) are not affected.
- **Request shape.**
  `POST` requires `Content-Type: application/json`, which also forces browsers to send a CORS preflight for cross-origin calls, so a page on a refused origin cannot make the server run the engine with a simple form post.
  Body size and design size are capped as described above.
- **Asset ids.**
  The official renderer opens `brand_kit/assets/<asset_id>` without checking that the result stays in that folder, so `POST /api/resize` returns 400 for any `asset_id` that is not a plain file name: no `/` or `\`, no `..`, no drive letter or other `:`, no control characters, no surrounding whitespace, and not `.` or empty.
  Without this check an absolute path or a `../` path would render an arbitrary image file from your machine into the returned PNG.
  A plain name that is not in the brand kit is still accepted and rendered as the renderer's "missing asset" placeholder.

The API is read-only and serves only the repository's samples and brand files, but do not expose it on a network you do not trust.

## Tests

```
.venv/bin/python -m unittest discover -s webapp/tests -t . -v
```

The tests start the server on an ephemeral port and exercise every endpoint, including a real resize of the level-1 sample, CORS preflight, the Host, Origin and Content-Type policy, path-like `asset_id` values, bad input, request framing, the advertised default pipeline, binding `localhost` on both IPv4 and IPv6, and a simulated engine failure.

## Notes

- Scores and metrics are local proxies from `pipelines/common/quality.py`, not official challenge scores.
- A missing asset (for example in the level-3 sample) is painted by the renderer as a labeled placeholder and listed under renderer warnings.
- Temporary render files are written to `output/webapp/render-tmp/` and deleted immediately after each render.
