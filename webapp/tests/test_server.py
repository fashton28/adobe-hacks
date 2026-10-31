"""End-to-end tests for the viewer HTTP API (stdlib only).

Run from the repo root: .venv/bin/python -m unittest discover -s webapp/tests -t . -v
"""

import base64
import contextlib
import io
import json
import os
import socket
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from webapp.__main__ import main as cli_main
from webapp.server import (
    MAX_BODY_BYTES,
    MAX_ELEMENTS,
    allowed_hosts,
    make_server,
    make_servers,
    origin_matches,
    server_url,
)

ROOT = Path(__file__).resolve().parents[2]
LEVEL1 = ROOT / "input" / "chameleon_sample_level1_warmup.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data_url: str) -> tuple[int, int]:
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix), data_url[:40]
    raw = base64.b64decode(data_url[len(prefix):])
    assert raw[:8] == PNG_SIGNATURE
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server("127.0.0.1", 0, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, method="GET", body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = dict(headers or {})
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def get_json(self, path, expect=200, headers=None):
        status, response_headers, body = self.request(path, headers=headers)
        self.assertEqual(status, expect, body[:300])
        self.assertEqual(response_headers.get("Vary"), "Origin")
        self.assertTrue(response_headers["Content-Type"].startswith("application/json"))
        return json.loads(body)

    def post_json(self, body, expect=200, raw=None, headers=None):
        status, response_headers, payload = self.request("/api/resize", "POST", body=body, raw=raw, headers=headers)
        self.assertEqual(status, expect, payload[:500])
        self.assertEqual(response_headers.get("Vary"), "Origin")
        return json.loads(payload)

    # ---- GET endpoints

    def test_health(self):
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_formats(self):
        from pipelines.common.formats import FORMATS

        self.assertEqual(self.get_json("/api/formats"), {"formats": FORMATS})

    def test_pipelines(self):
        import pipelines

        with patch.dict(os.environ):
            os.environ.pop("CHAMELEON_PIPELINE", None)
            data = self.get_json("/api/pipelines")
            self.assertEqual(data["pipelines"], list(pipelines.PIPELINES))
            self.assertEqual(data["default"], pipelines.DEFAULT)
            os.environ["CHAMELEON_PIPELINE"] = "anchored"
            self.assertEqual(self.get_json("/api/pipelines")["default"], "anchored")
            os.environ["CHAMELEON_PIPELINE"] = "no-such-pipeline"
            self.assertEqual(self.get_json("/api/pipelines")["default"], pipelines.DEFAULT)

    def test_default_pipeline_matches_advertised_default(self):
        """A request without "pipeline" runs exactly what /api/pipelines calls the default."""
        task = json.loads(LEVEL1.read_text())
        body = {"source": task["source"], "target_canvas": task["target_canvas"]}
        for env in ("anchored", "no-such-pipeline"):
            with self.subTest(env=env), patch.dict(os.environ, {"CHAMELEON_PIPELINE": env}):
                advertised = self.get_json("/api/pipelines")["default"]
                self.assertEqual(self.post_json(body)["pipeline"], advertised)

    def test_samples_list_and_fetch(self):
        samples = self.get_json("/api/samples")["samples"]
        by_key = {(s["dir"], s["name"]): s for s in samples}
        level1 = by_key[("input", LEVEL1.stem)]
        task = json.loads(LEVEL1.read_text())
        self.assertEqual(level1["task_id"], task["task_id"])
        self.assertEqual(level1["difficulty_label"], task["difficulty_label"])
        self.assertEqual(level1["canvas"], task["source"]["canvas"])
        self.assertEqual(level1["target_canvas"], task["target_canvas"])
        self.assertEqual(level1["element_count"], len(task["source"]["elements"]))
        self.assertIn(("fixtures", "editorial"), by_key)
        self.assertTrue(all(d in ("input", "fixtures") or d.startswith("heldout") for d in {s["dir"] for s in samples}))
        for heldout in sorted((ROOT / "tests").glob("heldout*")):
            if any(heldout.glob("*.json")):
                self.assertIn(heldout.name, {s["dir"] for s in samples})
        self.assertEqual(self.get_json(f"/api/samples/input/{LEVEL1.stem}"), task)

    def test_sample_not_found_and_traversal(self):
        for path in ("/api/samples/input/nope", "/api/samples/secret/x",
                     "/api/samples/input/..%2F..%2Frequirements", "/api/samples/input/a/b"):
            self.assertIn("error", self.get_json(path, expect=404), path)

    def test_static_assets_fonts(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"/app.js", body)
        for path, ctype in (("/app.js", "javascript"), ("/app.css", "text/css"),
                            ("/assets/solstice_logo_lockup.png", "image/png"),
                            ("/fonts/SolsticeSans-Regular.ttf", "font/ttf")):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, headers["Content-Type"], path)
        for path in ("/assets/../server.py", "/assets/%2E%2E/README.md", "/../webapp/server.py",
                     "/fonts/missing.ttf", "/api/unknown"):
            status, _, _ = self.request(path)
            self.assertEqual(status, 404, path)

    # ---- CORS, Host and Origin policy

    ALLOWED_ORIGINS = (
        "https://new.express.adobe.com",                 # Adobe Express itself
        "https://express.adobe.com",
        "https://abc123def.wxp.adobe-addons.com",        # a published add-on panel
        "https://localhost:5241",                        # the add-on dev server
        "http://localhost:8765",
        "http://127.0.0.1:9000",
        "http://[::1]:8765",
    )
    REFUSED_ORIGINS = (
        "https://evil.example",
        "http://express.adobe.com",                      # Adobe origins must be https
        "https://adobe.com.evil.example",
        "https://evil-adobe.com",
        "https://adobe-addons.com.evil.example",
        "http://localhost.evil.example:8765",
        "null",                                          # sandboxed iframes, file:// pages
        "not an origin",
    )

    def test_cors_preflight(self):
        for origin in self.ALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                status, headers, body = self.request("/api/resize", "OPTIONS", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                    "Access-Control-Request-Private-Network": "true",
                })
                self.assertEqual(status, 204)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
                self.assertEqual(headers["Vary"], "Origin")
                self.assertIn("POST", headers["Access-Control-Allow-Methods"])
                self.assertIn("content-type", headers["Access-Control-Allow-Headers"].lower())
                self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")

    def test_allowed_origin_is_echoed(self):
        status, headers, _ = self.request("/api/health", headers={"Origin": "https://x1.wxp.adobe-addons.com"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://x1.wxp.adobe-addons.com")

    def test_no_origin_means_no_cors_headers(self):
        status, headers, _ = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["Vary"], "Origin")

    def test_refused_origins(self):
        task = json.loads(LEVEL1.read_text())
        for origin in self.REFUSED_ORIGINS:
            with self.subTest(origin=origin):
                for method, path, body in (("OPTIONS", "/api/resize", None), ("GET", "/api/samples", None),
                                           ("POST", "/api/resize", {"task": task})):
                    with patch("webapp.server.run_engine") as engine:
                        status, headers, payload = self.request(path, method, body=body, headers={"Origin": origin})
                    self.assertEqual(status, 403, (method, payload[:200]))
                    self.assertNotIn("Access-Control-Allow-Origin", headers)
                    self.assertIn("not allowed", json.loads(payload)["error"])
                    engine.assert_not_called()
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_same_origin_is_allowed(self):
        """The viewer's own page sends Origin == its own URL on POST."""
        port = self.server.server_address[1]
        status, headers, _ = self.request("/api/health", headers={"Origin": f"http://127.0.0.1:{port}"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], f"http://127.0.0.1:{port}")

    def test_host_header_is_validated(self):
        """DNS rebinding: a foreign name resolving to 127.0.0.1 must be refused."""
        port = self.server.server_address[1]
        for host in (f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}", f"LOCALHOST:{port}"):
            with self.subTest(host=host):
                self.assertEqual(self.get_json("/api/health", headers={"Host": host}), {"ok": True})
        for host in (f"evil.example:{port}", "localhost", f"localhost:{port + 1}", f"127.0.0.2:{port}",
                     f"localhost.:{port}", f"0.0.0.0:{port}"):
            with self.subTest(host=host):
                data = self.get_json("/api/samples", expect=403, headers={"Host": host})
                self.assertIn("not allowed", data["error"])
        reply = self.raw_exchange(b"GET /api/health HTTP/1.0\r\n\r\n")
        self.assertIn(b" 400 ", reply.split(b"\r\n", 1)[0])
        self.assertIn(b"missing Host header", reply)

    def test_post_requires_json_content_type(self):
        task = json.loads(LEVEL1.read_text())
        raw = json.dumps({"task": task}).encode()
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                      "application/jsonx"):
            with self.subTest(ctype=ctype), patch("webapp.server.run_engine") as engine:
                data = self.post_json(None, expect=415, raw=raw, headers={"Content-Type": ctype})
                self.assertIn("application/json", data["error"])
                engine.assert_not_called()
        port = self.server.server_address[1]
        reply = self.raw_exchange(b"POST /api/resize HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Length: %d\r\n\r\n"
                                  % (port, len(raw)) + raw)
        self.assertIn(b" 415 ", reply.split(b"\r\n", 1)[0])
        self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
        data = self.post_json(None, raw=raw, headers={"Content-Type": "application/json; charset=utf-8"})
        self.check_resize(data, task)

    def test_too_many_elements(self):
        element = {"type": "shape", "shape_type": "rectangle", "x": 0, "y": 0, "width": 1, "height": 1,
                   "fill_color": "rgba(0,0,0,1)"}
        source = {"canvas": {"width": 100, "height": 100},
                  "elements": [{**element, "id": f"e{i}"} for i in range(MAX_ELEMENTS + 1)]}
        with patch("webapp.server.run_engine") as engine:
            data = self.post_json({"source": source, "target_canvas": {"width": 50, "height": 50}}, expect=400)
        self.assertIn(str(MAX_ELEMENTS), data["error"])
        engine.assert_not_called()

    # ---- resize

    def check_resize(self, data, task, pipeline=None):
        target = task["target_canvas"]
        for key in ("output", "validation", "metrics", "score", "pipeline", "elapsed_ms",
                    "warnings", "source_png", "output_png"):
            self.assertIn(key, data)
        self.assertEqual(data["output"]["canvas"], target)
        self.assertEqual(sorted(e["id"] for e in data["output"]["elements"]),
                         sorted(e["id"] for e in task["source"]["elements"]))
        self.assertEqual(data["validation"], [])
        self.assertIsInstance(data["score"], (int, float))
        self.assertGreaterEqual(data["elapsed_ms"], 0)
        self.assertIn("min_font", data["metrics"])
        self.assertIsInstance(data["warnings"], list)
        if pipeline:
            self.assertEqual(data["pipeline"], pipeline)
        self.assertEqual(png_size(data["output_png"]), (target["width"], target["height"]))
        canvas = task["source"]["canvas"]
        self.assertEqual(png_size(data["source_png"]), (canvas["width"], canvas["height"]))

    def test_resize_level1(self):
        task = json.loads(LEVEL1.read_text())
        data = self.post_json({"source": task["source"], "target_canvas": task["target_canvas"]})
        self.check_resize(data, task)
        self.assertEqual(data["pipeline"], self.get_json("/api/pipelines")["default"])

    def test_resize_full_task_and_pipeline(self):
        task = json.loads(LEVEL1.read_text())
        task["target_canvas"] = {"width": 1280, "height": 720}
        data = self.post_json({"task": task, "pipeline": "anchored"})
        self.check_resize(data, task, pipeline="anchored")

    def test_resize_bad_input(self):
        task = json.loads(LEVEL1.read_text())
        cases = [
            [],
            {},
            {"source": task["source"]},
            {"source": task["source"], "target_canvas": {"width": 0, "height": 100}},
            {"source": task["source"], "target_canvas": {"width": "1", "height": 100}},
            {"source": task["source"], "target_canvas": {"width": 9000, "height": 100}},
            {"source": {"canvas": {"width": 10, "height": 10}, "elements": []}, "target_canvas": {"width": 5, "height": 5}},
            {"source": {"canvas": {"width": 10, "height": 10}, "elements": [{"type": "text"}]},
             "target_canvas": {"width": 5, "height": 5}},
            {"source": {"canvas": {"width": 10, "height": 10}, "elements": [{"id": "a", "type": "shape"}]},
             "target_canvas": {"width": 5, "height": 5}},
            {"task": "nope"},
            {"task": task, "pipeline": "does-not-exist"},
            {"task": task, "pipeline": ["anchored"]},
        ]
        for body in cases:
            with self.subTest(body=str(body)[:80]):
                data = self.post_json(body, expect=400)
                self.assertIsInstance(data["error"], str)
                self.assertTrue(data["error"])
        self.assertIn("error", self.post_json(None, expect=400, raw=b"{not json"))
        self.assertIn("error", self.post_json(None, expect=400, raw=b""))
        self.assertIn("error", self.post_json(None, expect=415))  # No body, no Content-Type.
        # The server must keep answering after bad requests.
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    # ---- asset_id containment

    @staticmethod
    def image_task(asset_id):
        source = {"canvas": {"width": 200, "height": 200}, "elements": [
            {"id": "bg", "type": "shape", "shape_type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 200,
             "fill_color": "rgba(255,255,255,1)", "z_index": 0},
            {"id": "img", "type": "image", "asset_id": asset_id, "x": 50, "y": 50, "width": 100, "height": 100,
             "z_index": 1},
        ]}
        return {"source": source, "target_canvas": {"width": 160, "height": 120}}

    def test_path_like_asset_ids_are_refused(self):
        """The renderer opens assets_dir / asset_id, so paths would read arbitrary host images."""
        real_image = ROOT / "brand_kit" / "assets" / "solstice_bottle.png"
        self.assertTrue(real_image.is_file())
        cases = (
            str(real_image),                                # absolute POSIX path to a real image
            "../assets/solstice_bottle.png",                # relative traversal back to a real image
            "../../../../../../../etc/hosts",
            "..",
            ".",
            "sub/solstice_bottle.png",                      # any separator, even inside the folder
            "..\\..\\secret.png",                           # Windows separators
            "C:\\Windows\\secret.png",
            "C:secret.png",                                 # drive-relative
            "solstice_bottle.png\x00.txt",
            " solstice_bottle.png",
            "",
            42,
        )
        for asset_id in cases:
            with self.subTest(asset_id=asset_id), patch("webapp.server.run_engine") as engine, \
                    patch("renderer.converter.convert.render_design_to_png") as render:
                data = self.post_json(self.image_task(asset_id), expect=400)
                self.assertIn("asset_id", data["error"])
                engine.assert_not_called()
                render.assert_not_called()
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_plain_asset_ids_render(self):
        """Known assets render; an unknown plain name still gets the renderer placeholder."""
        for asset_id, missing in (("solstice_bottle.png", False), ("not_in_brand_kit_v2.png", True),
                                  ("logo final (1).PNG", True)):
            with self.subTest(asset_id=asset_id):
                task = self.image_task(asset_id)
                data = self.post_json(task)
                self.assertEqual(png_size(data["output_png"]), (160, 120))
                self.assertEqual(any(asset_id in w for w in data["warnings"]), missing, data["warnings"])

    def test_render_png_refuses_unsafe_designs(self):
        """Defence in depth: designs reaching the renderer by any path are checked too."""
        from webapp.server import BadRequest, render_png

        design = self.image_task("/etc/hosts")["source"]
        with patch("renderer.converter.convert.render_design_to_png") as render, self.assertRaises(BadRequest):
            render_png(design)
        render.assert_not_called()

    def raw_exchange(self, request: bytes) -> bytes:
        """Send raw bytes on one connection and return everything the server sends back."""
        with socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=10) as sock:
            sock.sendall(request)
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks)

    def test_unframed_bodies_close_the_connection(self):
        """Bodies the server will not read must not be parsed as a follow-up request."""
        host = b"Host: 127.0.0.1:%d\r\n" % self.server.server_address[1]
        smuggled = b"GET /api/health HTTP/1.1\r\n" + host + b"\r\n"
        cases = {
            "chunked": b"Transfer-Encoding: chunked\r\n\r\n" + b"%x\r\n" % len(smuggled) + smuggled + b"\r\n0\r\n\r\n",
            "bad length": b"Content-Length: abc\r\n\r\n" + smuggled,
            "too large": b"Content-Length: %d\r\n\r\n" % (MAX_BODY_BYTES + 1) + smuggled,
        }
        for name, rest in cases.items():
            with self.subTest(name):
                reply = self.raw_exchange(b"POST /api/resize HTTP/1.1\r\n" + host
                                          + b"Content-Type: application/json\r\n" + rest)
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1, reply[:300])
                self.assertRegex(reply.split(b"\r\n", 1)[0], rb" 4(00|13) ")

    def test_engine_failure_returns_500(self):
        task = json.loads(LEVEL1.read_text())
        with patch("webapp.server.run_engine", side_effect=RuntimeError("boom")):
            data = self.post_json({"task": task}, expect=500)
        self.assertIn("boom", data["error"])
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_concurrent_requests(self):
        task = json.loads(LEVEL1.read_text())
        results, errors = [], []

        def worker(width):
            try:
                body = {"source": task["source"], "target_canvas": {"width": width, "height": 600}}
                status, _, payload = self.request("/api/resize", "POST", body=body)
                results.append((width, status, json.loads(payload)))
            except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(w,)) for w in (600, 900, 1200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 3)
        for width, status, payload in results:
            self.assertEqual(status, 200)
            self.assertEqual(png_size(payload["output_png"]), (width, 600))


class PolicyTest(unittest.TestCase):
    """Pure functions behind the Host and Origin checks, and the CLI flag."""

    def test_allowed_hosts(self):
        for bind in ("localhost", "127.0.0.1", "::1", "[::1]"):
            self.assertEqual(allowed_hosts(bind, 8765),
                             {"localhost:8765", "127.0.0.1:8765", "[::1]:8765"}, bind)
        self.assertIn("localhost", allowed_hosts("127.0.0.1", 80))
        for bind in ("0.0.0.0", "::", "", "192.168.1.20"):
            self.assertIsNone(allowed_hosts(bind, 8765), bind)

    def test_origin_matches(self):
        cases = [
            ("https://a.b.adobe.com", "https://*.adobe.com", True),
            ("https://adobe.com", "https://*.adobe.com", False),
            ("https://a.adobe.com:8443", "https://*.adobe.com", True),
            ("https://a.adobe.com.evil", "https://*.adobe.com", False),
            ("https://xadobe.com", "https://*.adobe.com", False),
            ("http://a.adobe.com", "https://*.adobe.com", False),
            ("https://example.com", "https://example.com", True),
            ("https://example.com:444", "https://example.com:443", False),
            ("https://example.com/path", "https://example.com", False),
            ("https://user@example.com", "https://example.com", False),
            ("null", "https://example.com", False),
            ("https://example.com:99999", "https://example.com", False),
            ("anything", "*", True),
        ]
        for origin, pattern, expected in cases:
            self.assertEqual(origin_matches(origin, pattern), expected, (origin, pattern))

    def test_allow_origin_flag(self):
        server = make_server("127.0.0.1", 0, quiet=True, allow_origins=["https://*.example.org"])
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}/api/health"
        for origin, expected in (("https://a.example.org", 200), ("https://new.express.adobe.com", 200),
                                 ("https://example.net", 403)):
            req = urllib.request.Request(base, headers={"Origin": origin})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status, acao = resp.status, resp.headers.get("Access-Control-Allow-Origin")
            except urllib.error.HTTPError as err:
                status, acao = err.code, err.headers.get("Access-Control-Allow-Origin")
            self.assertEqual(status, expected, origin)
            self.assertEqual(acao, origin if expected == 200 else None, origin)

    def test_allow_any_origin(self):
        server = make_server("127.0.0.1", 0, quiet=True, allow_origins=["*"])
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/health",
                                     headers={"Origin": "https://evil.example"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.headers["Access-Control-Allow-Origin"], "*")

    def test_cli_rejects_malformed_allow_origin(self):
        for bad in ("example.com", "https://example.com/", "ftp://example.com"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stderr(io.StringIO()):
                cli_main(["--port", "0", "--allow-origin", bad])
            self.assertEqual(ctx.exception.code, 2)


class LocalhostBindTest(unittest.TestCase):
    """`make_servers("localhost")` must answer on both loopback families."""

    def test_localhost_binds_ipv4_and_ipv6(self):
        servers = make_servers("localhost", 0, quiet=True)
        self.addCleanup(lambda: [s.server_close() for s in servers])
        families = {s.address_family for s in servers}
        self.assertIn(socket.AF_INET, families)
        if not socket.has_ipv6 or len(servers) == 1:
            self.skipTest("no IPv6 loopback on this machine")
        self.assertEqual(families, {socket.AF_INET, socket.AF_INET6})
        self.assertEqual(len({s.server_address[1] for s in servers}), 1)
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for t in threads:
            t.start()
        self.addCleanup(lambda: [s.shutdown() for s in servers])
        port = servers[0].server_address[1]
        for host in ("127.0.0.1", "[::1]"):
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=10) as resp:
                self.assertEqual(json.loads(resp.read()), {"ok": True}, host)
        self.assertEqual(server_url(servers[0]), f"http://localhost:{port}")

    def test_explicit_host_binds_only_that_address(self):
        servers = make_servers("127.0.0.1", 0, quiet=True)
        self.addCleanup(lambda: [s.server_close() for s in servers])
        self.assertEqual([s.server_address[0] for s in servers], ["127.0.0.1"])


if __name__ == "__main__":
    unittest.main()
