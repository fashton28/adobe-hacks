"""CHAMELEON local viewer: a stdlib HTTP server around the engine and the official renderer.

The HTTP API is a stable contract shared with the Adobe Express add-on:

    GET  /api/health                 -> {"ok": true}
    GET  /api/formats                -> {"formats": [...]}
    GET  /api/pipelines              -> {"pipelines": [...], "default": name}
    GET  /api/samples                -> {"samples": [...]}
    GET  /api/samples/<dir>/<name>   -> raw task JSON
    POST /api/resize                 -> output design, diagnostics and rendered PNGs

Browser-facing hardening (the server runs on the user's machine and any web
page they visit can try to reach it):

- Host header: on a loopback bind only `localhost`, `127.0.0.1` and `[::1]`
  with the bound port are accepted (403 otherwise), which defeats DNS
  rebinding. Binding any other address (`--host`) accepts any Host.
- Origin: a request that carries an `Origin` header is answered only when the
  origin is the server itself, a loopback origin (any port, http or https),
  `https://*.adobe.com` or `https://*.adobe-addons.com` (the Express add-on
  panel, including `https://<id>.wxp.adobe-addons.com`), or matches an extra
  `--allow-origin` pattern (403 otherwise). Allowed origins are echoed in
  `Access-Control-Allow-Origin` with `Vary: Origin`; OPTIONS preflights are
  answered for them, including Chrome's Private Network Access header.
- POST bodies must be `Content-Type: application/json` (415 otherwise), which
  also forces a CORS preflight for cross-origin callers, carry a
  `Content-Length` of at most MAX_BODY_BYTES (413) and hold at most
  MAX_ELEMENTS source elements (400).

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
MAX_ELEMENTS = 500
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
    elements = source.get("elements")
    if isinstance(elements, list) and len(elements) > MAX_ELEMENTS:
        raise BadRequest(f"source has {len(elements)} elements; at most {MAX_ELEMENTS} are accepted")
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


# --------------------------------------------------------------------------- request policy

LOOPBACK_NAMES = ("localhost", "127.0.0.1", "[::1]")
# Origins allowed to call the API from a browser by default: loopback pages on
# any port (the viewer itself, the add-on dev server at https://localhost:5241)
# and Adobe Express plus its add-on sandboxes (https://<id>.wxp.adobe-addons.com).
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost", "https://localhost",
    "http://127.0.0.1", "https://127.0.0.1",
    "http://[::1]", "https://[::1]",
    "https://*.adobe.com",
    "https://*.adobe-addons.com",
)


def allowed_hosts(bind_host: str, port: int) -> frozenset[str] | None:
    """Host header values accepted by a server bound to `bind_host`:`port`.

    Loopback binds accept only the loopback names with the bound port (and the
    bare names on port 80), so a rebound DNS name pointing at 127.0.0.1 is
    refused. Any other bind returns None, meaning every Host is accepted: the
    user chose to expose the server under names it cannot know.
    """
    if bind_host.strip("[]").lower() not in ("localhost", "127.0.0.1", "::1"):
        return None
    hosts = {f"{name}:{port}" for name in LOOPBACK_NAMES}
    if port == 80:
        hosts.update(LOOPBACK_NAMES)
    return frozenset(hosts)


def _split_origin(origin: str) -> tuple[str, str, int | None] | None:
    """('https', 'host', port or None) for a serialized origin, None if malformed."""
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query \
            or parts.fragment or parts.username or parts.password:
        return None
    return parts.scheme, parts.hostname.lower(), port


def origin_matches(origin: str, pattern: str) -> bool:
    """Match an Origin header against `scheme://host[:port]` or `scheme://*.domain[:port]`.

    `*.domain` matches subdomains only (not the bare domain). A pattern without
    a port matches any port; "*" matches every origin.
    """
    if pattern == "*":
        return True
    got, want = _split_origin(origin), _split_origin(pattern.replace("://*.", "://wildcard.", 1))
    if got is None or want is None or got[0] != want[0]:
        return False
    if want[2] is not None and got[2] != want[2]:
        return False
    if pattern.split("://", 1)[1].startswith("*."):
        return got[1].endswith("." + want[1][len("wildcard."):])
    return got[1] == want[1]


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
    # Set per server by make_server: accepted Host values (None = any) and the
    # Origin patterns allowed in addition to the server's own origin.
    allowed_hosts: frozenset[str] | None = None
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    _cors_origin: str | None = None

    # ---- plumbing

    def log_message(self, format: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(format, *args)

    def _cors(self) -> None:
        self.send_header("Vary", "Origin")
        if self._cors_origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", self._cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")

    def _admit(self) -> bool:
        """Apply the Host and Origin policy; send 400/403 and return False on refusal."""
        self._cors_origin = None
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return self._refuse(HTTPStatus.BAD_REQUEST, "missing Host header")
        if self.allowed_hosts is not None and host not in self.allowed_hosts:
            return self._refuse(HTTPStatus.FORBIDDEN, f"host {host!r} is not allowed; "
                                "open the viewer via localhost, 127.0.0.1 or [::1]")
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # Not a cross-origin browser request (curl, navigation, same-origin GET).
        if "*" in self.allowed_origins:
            self._cors_origin = "*"
            return True
        if origin_matches(origin, f"http://{host}") or any(origin_matches(origin, p) for p in self.allowed_origins):
            self._cors_origin = origin
            return True
        return self._refuse(HTTPStatus.FORBIDDEN, f"origin {origin!r} is not allowed "
                            "(start the server with --allow-origin to permit it)")

    def _refuse(self, status: int, message: str) -> bool:
        self.close_connection = True  # Any request body stays unread.
        with contextlib.suppress(OSError):
            self._error(status, message)
        return False

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
        if not self._admit():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        if self._cors_origin is not None and self.headers.get("Access-Control-Request-Private-Network") == "true":
            # Chrome's Private Network Access preflight (public page -> localhost).
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if self._admit():
            self._guard(self._get)

    def do_POST(self) -> None:
        if self._admit():
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
        if self.headers.get_content_type() != "application/json":
            self.close_connection = True  # The unread body would be parsed as the next request.
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
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


def make_server(host: str = "127.0.0.1", port: int = 8765, quiet: bool = False,
                allow_origins: tuple[str, ...] | list[str] = ()) -> ThreadingHTTPServer:
    """Bind one listening socket. IPv6 literals ("::1", "::") get an IPv6 socket.

    `allow_origins` adds Origin patterns (see `origin_matches`) to
    DEFAULT_ALLOWED_ORIGINS; "*" allows every origin.
    """
    handler = type("ChameleonHandler", (Handler,), {
        "quiet": quiet, "allowed_origins": DEFAULT_ALLOWED_ORIGINS + tuple(allow_origins)})
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("ChameleonServer", (_Server,), {"address_family": family})
    server = server_class((host, port), handler)
    handler.allowed_hosts = allowed_hosts(host, server.server_address[1])
    return server


LOCALHOST = "localhost"


def make_servers(host: str = LOCALHOST, port: int = 8765, quiet: bool = False,
                 allow_origins: tuple[str, ...] | list[str] = ()) -> list[ThreadingHTTPServer]:
    """Bind the viewer; "localhost" means both 127.0.0.1 and ::1 on the same port.

    Browsers may resolve localhost to either address, so binding only one of them
    makes http://localhost:<port> fail on some machines. If the machine has no IPv6
    loopback, the IPv4 socket alone is used. Any other host binds exactly that address.
    """
    if host != LOCALHOST:
        return [make_server(host, port, quiet, allow_origins)]
    for _attempt in range(5 if port == 0 else 1):
        first = make_server("127.0.0.1", port, quiet, allow_origins)
        chosen = first.server_address[1]
        try:
            return [first, make_server("::1", chosen, quiet, allow_origins)]
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
