"""End-to-end tests for the viewer HTTP API (stdlib only).

Run from the repo root: .venv/bin/python -m unittest discover -s webapp/tests -t . -v
"""

import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp.server import make_server

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
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def get_json(self, path, expect=200):
        status, headers, body = self.request(path)
        self.assertEqual(status, expect, body[:300])
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        return json.loads(body)

    def post_json(self, body, expect=200, raw=None):
        status, headers, payload = self.request("/api/resize", "POST", body=body, raw=raw)
        self.assertEqual(status, expect, payload[:500])
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        return json.loads(payload)

    # ---- GET endpoints

    def test_health(self):
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_formats(self):
        from pipelines.common.formats import FORMATS

        self.assertEqual(self.get_json("/api/formats"), {"formats": FORMATS})

    def test_pipelines(self):
        import pipelines

        data = self.get_json("/api/pipelines")
        self.assertEqual(data["pipelines"], list(pipelines.PIPELINES))
        self.assertEqual(data["default"], pipelines.DEFAULT)

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
        self.assertTrue({s["dir"] for s in samples} <= {"input", "fixtures", "heldout"})
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

    # ---- CORS

    def test_cors_preflight(self):
        status, headers, body = self.request("/api/resize", "OPTIONS", headers={
            "Origin": "https://express.adobe.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertIn("POST", headers["Access-Control-Allow-Methods"])
        self.assertIn("content-type", headers["Access-Control-Allow-Headers"].lower())

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
        import os

        import pipelines

        self.assertEqual(data["pipeline"], os.environ.get("CHAMELEON_PIPELINE") or pipelines.DEFAULT)

    def test_resize_full_task_and_pipeline(self):
        task = json.loads(LEVEL1.read_text())
        task["target_canvas"] = {"width": 1280, "height": 720}
        data = self.post_json({"task": task, "pipeline": "anchored"})
        self.check_resize(data, task, pipeline="anchored")

    def test_resize_bad_input(self):
        task = json.loads(LEVEL1.read_text())
        cases = [
            None,
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
        ]
        for body in cases:
            with self.subTest(body=str(body)[:80]):
                data = self.post_json(body, expect=400)
                self.assertIsInstance(data["error"], str)
                self.assertTrue(data["error"])
        self.assertIn("error", self.post_json(None, expect=400, raw=b"{not json"))
        self.assertIn("error", self.post_json(None, expect=400, raw=b""))
        # The server must keep answering after bad requests.
        self.assertEqual(self.get_json("/api/health"), {"ok": True})

    def test_engine_failure_returns_500(self):
        from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
