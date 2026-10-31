"""CHAMELEON local viewer: a stdlib HTTP server around the engine and the official renderer.

The HTTP API is a stable contract shared with the Adobe Express add-on:

    GET  /api/health                 -> {"ok": true}
    GET  /api/formats                -> {"formats": [...]}
    GET  /api/pipelines              -> {"pipelines": [...], "default": name}
    GET  /api/samples                -> {"samples": [...]}
    GET  /api/samples/<dir>/<name>   -> raw task JSON
    POST /api/resize                 -> output design, diagnostics and rendered PNGs

Every response carries `Access-Control-Allow-Origin: *` and OPTIONS preflights
are answered, so browser-hosted clients on other origins can call it.
Static files are served from `webapp/static/`, brand assets from `/assets/` and
brand fonts from `/fonts/` (all read-only).
"""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import importlib
import json
import math
import mimetypes
import os
import re
import socket
import socketserver
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = ROOT / "brand_kit" / "assets"
FONTS_DIR = ROOT / "brand_kit" / "fonts"
RENDER_TMP = ROOT / "output" / "webapp" / "render-tmp"
# Sample folders by API name: the challenge inputs, the test fixtures and every
# held-out corpus (tests/heldout, tests/heldout2, ...), discovered at import time.
SAMPLE_DIRS = {
    "input": ROOT / "input",
    "fixtures": ROOT / "tests" / "fixtures",
    **{path.name: path for path in sorted((ROOT / "tests").glob("heldout*")) if path.is_dir()},
}

if str(ROOT) not in sys.path:  # Allow `python webapp/server.py` as well as `-m webapp`.
    sys.path.insert(0, str(ROOT))

MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_CANVAS_SIDE = 8192
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")

# The engine's measurement caches and the renderer's shared font manager are
# not documented as thread-safe, so compute work runs one request at a time.
_COMPUTE_LOCK = threading.Lock()
_SOURCE_PNG_CACHE: OrderedDict[str, tuple[str, list[str]]] = OrderedDict()
_SOURCE_PNG_CACHE_SIZE = 16


class BadRequest(ValueError):
    """Client error reported as HTTP 400 with {"error": message}."""


# --------------------------------------------------------------------------- engine


def _api_module():
    """Return `pipelines.api` when it exists, else None (re-checked on each call)."""
    try:
        return importlib.import_module("pipelines.api")
    except ModuleNotFoundError as exc:
        if exc.name in ("pipelines.api",):
            return None
        raise


def pipeline_names() -> tuple[list[str], str]:
    """Return (available names, the pipeline a request without "pipeline" will use).

    The default mirrors the engine CLI: CHAMELEON_PIPELINE when it names a known
    pipeline, else `pipelines.DEFAULT`. An unknown env value is ignored here (the
    viewer warns about it at startup) instead of failing every request.
    """
    import pipelines

    names = list(pipelines.PIPELINES)
    env = os.environ.get("CHAMELEON_PIPELINE")
    return names, env if env in names else pipelines.DEFAULT


def run_engine(source: dict, target: dict, pipeline: str | None = None) -> dict:
    """Resize `source` to `target` and return output/validation/metrics/score/pipeline/elapsed_ms."""
    api = _api_module()
    if api is not None and hasattr(api, "run"):
        result = api.run(source, target, pipeline)
        return {key: result.get(key) for key in ("output", "validation", "metrics", "score", "pipeline", "elapsed_ms")}

    import pipelines
    from pipelines.common.quality import metrics, score
    from pipelines.common.validate import validate

    name = pipeline or pipeline_names()[1]
    resize = pipelines.get_pipeline(name)
    started = time.perf_counter()
    output = resize(source, {"width": target["width"], "height": target["height"]})
    elapsed_ms = (time.perf_counter() - started) * 1000
    problems = validate(source, target, output)
    if problems:
        # Metrics assume a structurally sound design; report validation only.
        return {"output": output, "validation": problems, "metrics": {}, "score": None,
                "pipeline": name, "elapsed_ms": elapsed_ms}
    return {"output": output, "validation": problems, "metrics": metrics(source, output),
            "score": score(source, output), "pipeline": name, "elapsed_ms": elapsed_ms}


def render_png(design: dict) -> tuple[str, list[str]]:
    """Render with the official renderer at native size; return (data URL, warnings)."""
    from renderer.converter.convert import render_design_to_png

    canvas = design["canvas"]
    native = max(math.ceil(canvas["width"]), math.ceil(canvas["height"]))
    RENDER_TMP.mkdir(parents=True, exist_ok=True)
    path = RENDER_TMP / f"{uuid.uuid4().hex}.png"
    try:
        warnings = render_design_to_png(design, ASSETS_DIR, path, max_size=native)
        data = path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii"), list(warnings or [])


def render_source_png(source: dict) -> tuple[str, list[str]]:
    key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    cached = _SOURCE_PNG_CACHE.get(key)
    if cached is not None:
        _SOURCE_PNG_CACHE.move_to_end(key)
        return cached
    result = render_png(source)
    _SOURCE_PNG_CACHE[key] = result
    while len(_SOURCE_PNG_CACHE) > _SOURCE_PNG_CACHE_SIZE:
        _SOURCE_PNG_CACHE.popitem(last=False)
    return result


def parse_resize_request(body: Any) -> tuple[dict, dict, str]:
    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")
    task = body.get("task")
    if task is not None:
        if not isinstance(task, dict):
            raise BadRequest("'task' must be a JSON object")
        source, target = task.get("source"), task.get("target_canvas")
    else:
        source, target = body.get("source"), body.get("target_canvas")
    if not isinstance(source, dict):
        raise BadRequest("missing 'source' design object (or a full task in 'task')")
    if not isinstance(target, dict):
        raise BadRequest("missing 'target_canvas' object with width and height")
    target = {"width": target.get("width"), "height": target.get("height")}
    pipeline = body.get("pipeline")
    names, default = pipeline_names()
    if pipeline in ("", None):
        pipeline = default  # Resolved here so the response names exactly what /api/pipelines advertised.
    elif not isinstance(pipeline, str) or pipeline not in names:
        raise BadRequest(f"unknown pipeline {pipeline!r}; available: {', '.join(names)}")

    from pipelines.common.validate import validate_input

    try:
        validate_input(source, target)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        detail = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
        raise BadRequest(f"invalid input: {detail}") from exc
    for name, canvas in (("source", source["canvas"]), ("target", target)):
        if max(canvas["width"], canvas["height"]) > MAX_CANVAS_SIDE:
            raise BadRequest(f"{name} canvas sides must be at most {MAX_CANVAS_SIDE}px")
    return source, target, pipeline


def resize_response(body: Any) -> dict:
    source, target, pipeline = parse_resize_request(body)
    with _COMPUTE_LOCK:
        result = run_engine(source, target, pipeline)
        output = result["output"]
        source_png, _ = render_source_png(source)
        output_png, warnings = render_png(output)
    return {**result, "warnings": warnings, "source_png": source_png, "output_png": output_png}


# --------------------------------------------------------------------------- samples


def list_samples() -> list[dict]:
    samples = []
    for dir_name, folder in SAMPLE_DIRS.items():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                source = task["source"]
                samples.append({
                    "name": path.stem,
                    "dir": dir_name,
                    "task_id": task.get("task_id", path.stem),
                    "difficulty_label": task.get("difficulty_label"),
                    "canvas": source["canvas"],
                    "target_canvas": task.get("target_canvas"),
                    "element_count": len(source.get("elements", [])),
                })
            except (OSError, ValueError, KeyError, TypeError):
                continue  # Not a task file; skip rather than break the listing.
    return samples


def load_sample(dir_name: str, name: str) -> dict | None:
    folder = SAMPLE_DIRS.get(dir_name)
    if folder is None or not _SAFE_NAME.match(name):
        return None
    path = folder / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- HTTP


def _json_safe(value: Any) -> Any:
    """Replace NaN/inf with None so the payload is strict JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _safe_file(base: Path, name: str) -> Path | None:
    """Resolve `name` inside `base`, refusing traversal and hidden files."""
    if not name or any(not _SAFE_NAME.match(part) for part in name.split("/")):
        return None
    path = (base / name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "ChameleonViewer/1.0"
    protocol_version = "HTTP/1.1"
    quiet = False
    # Socket read timeout: drops idle keep-alive connections and clients that stall
    # mid-request, so they cannot pin handler threads forever.
    timeout = 30

    # ---- plumbing

    def log_message(self, format: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(format, *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _file(self, path: Path | None, cache: str = "no-cache") -> None:
        if path is None:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, path.read_bytes(), ctype, cache)

    def _guard(self, fn) -> None:
        try:
            fn()
        except BadRequest as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - never let an engine/renderer failure kill the server
            if not self.quiet:
                traceback.print_exc()
            with contextlib.suppress(OSError):  # The client may already be gone.
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    # ---- verbs

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        self._guard(self._get)

    def do_POST(self) -> None:
        self._guard(self._post)

    def _get(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True})
        elif path == "/api/formats":
            from pipelines.common.formats import FORMATS

            self._json(HTTPStatus.OK, {"formats": FORMATS})
        elif path == "/api/pipelines":
            names, default = pipeline_names()
            self._json(HTTPStatus.OK, {"pipelines": names, "default": default})
        elif path == "/api/samples":
            self._json(HTTPStatus.OK, {"samples": list_samples()})
        elif path.startswith("/api/samples/"):
            parts = path[len("/api/samples/"):].split("/")
            task = load_sample(*parts) if len(parts) == 2 else None
            if task is None:
                self._error(HTTPStatus.NOT_FOUND, "sample not found")
            else:
                self._json(HTTPStatus.OK, task)
        elif path.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, f"unknown endpoint {path}")
        elif path.startswith("/assets/"):
            self._file(_safe_file(ASSETS_DIR, path[len("/assets/"):]), "public, max-age=3600")
        elif path.startswith("/fonts/"):
            self._file(_safe_file(FONTS_DIR, path[len("/fonts/"):]), "public, max-age=86400")
        elif path in ("/", "/index.html"):
            self._file(STATIC_DIR / "index.html")
        else:
            self._file(_safe_file(STATIC_DIR, path.lstrip("/")))

    def _post(self) -> None:
        path = urlsplit(self.path).path
        if path != "/api/resize":
            self._error(HTTPStatus.NOT_FOUND, f"unknown endpoint {path}")
            return
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True  # The unread body would be parsed as the next request.
            raise BadRequest("chunked request bodies are not supported; send Content-Length")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise BadRequest("invalid Content-Length") from None
        if length <= 0:
            raise BadRequest("request body is empty")
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        f"request body too large (limit {MAX_BODY_BYTES // (1024 * 1024)} MiB)")
            return
        raw = self.rfile.read(length)
        if len(raw) < length:
            self.close_connection = True
            raise BadRequest("request body ended early")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BadRequest(f"request body is not valid JSON: {exc}") from None
        self._json(HTTPStatus.OK, resize_response(body))


mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Browsers routinely drop keep-alive connections and abort superseded
        # requests; that is not a server error worth a traceback.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6 and self.server_address[0] == "::":
            # Wildcard IPv6 also accepts IPv4 (dual stack) where the OS allows it.
            with contextlib.suppress(OSError, AttributeError):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        # Skip HTTPServer.server_bind: its reverse DNS lookup (getfqdn) can stall for seconds.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


def make_server(host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> ThreadingHTTPServer:
    """Bind one listening socket. IPv6 literals ("::1", "::") get an IPv6 socket."""
    handler = type("ChameleonHandler", (Handler,), {"quiet": quiet})
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("ChameleonServer", (_Server,), {"address_family": family})
    return server_class((host, port), handler)


LOCALHOST = "localhost"


def make_servers(host: str = LOCALHOST, port: int = 8765, quiet: bool = False) -> list[ThreadingHTTPServer]:
    """Bind the viewer; "localhost" means both 127.0.0.1 and ::1 on the same port.

    Browsers may resolve localhost to either address, so binding only one of them
    makes http://localhost:<port> fail on some machines. If the machine has no IPv6
    loopback, the IPv4 socket alone is used. Any other host binds exactly that address.
    """
    if host != LOCALHOST:
        return [make_server(host, port, quiet)]
    for _attempt in range(5 if port == 0 else 1):
        first = make_server("127.0.0.1", port, quiet)
        chosen = first.server_address[1]
        try:
            return [first, make_server("::1", chosen, quiet)]
        except OSError as exc:
            if exc.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
                return [first]  # No IPv6 loopback on this machine.
            first.server_close()
            if port != 0 or exc.errno != errno.EADDRINUSE:
                raise
    raise OSError(errno.EADDRINUSE, "could not find a port free on both 127.0.0.1 and ::1")


def server_url(server: ThreadingHTTPServer, host: str = LOCALHOST) -> str:
    """Browser URL for a bound server; wildcard binds are shown as localhost."""
    port = server.server_address[1]
    if host in (LOCALHOST, "", "0.0.0.0", "::"):
        return f"http://localhost:{port}"
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"
