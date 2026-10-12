"""Regressions for layout selection, group fitting and evaluation gates."""

import contextlib
import copy
import io
import json
import subprocess
import sys
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pipelines import get_pipeline
from pipelines.adaptive.pipeline import search
from pipelines.common.quality import metrics
from pipelines.common.text import measure, _measure_uncached
from pipelines.common.validate import validate
from scripts.run_matrix import main as matrix_main, variants

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def temp_dir():
    # Inherit workspace permissions; TemporaryDirectory creates Windows ACLs
    # that exclude the managed sandbox identity even inside the workspace.
    parent = ROOT / "output" / "test-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"adaptive-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        if path.resolve().parent != parent.resolve():
            raise RuntimeError("Temporary cleanup escaped the test directory")
        shutil.rmtree(path)


def fixtures():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "tests/fixtures").glob("*.json"))]


class AdaptiveTests(unittest.TestCase):
    def test_text_cache_matches_uncached_metrics_after_typography_changes(self):
        el = copy.deepcopy(fixtures()[0]["source"]["elements"][4])
        modifications = ({}, {"content": "A replacement unbreakableword plus more copy"},
                         {"letter_spacing": 2.5}, {"font_weight": "bold", "font_style": "italic"},
                         {"style_runs": [{"start": 0, "end": 20, "font_weight": "bold", "font_style": "italic"}]})
        for change in modifications:
            updated = dict(el, **change)
            for size in (0.75, 9.5, 21, 32.25):
                for width in (60, 160, 600):
                    self.assertEqual(measure(updated, size, width), _measure_uncached(updated, size, width))

    def test_nearby_ratio_keeps_source_vertical_arrangement(self):
        task = json.loads((ROOT / "input/chameleon_sample_level1_warmup.json").read_text())
        out = get_pipeline("adaptive")(task["source"], task["target_canvas"])
        content = [e for e in out["elements"] if e.get("fit") != "cover"]
        centers = [e["y"] + e["height"] / 2 for e in content]
        self.assertLess(centers[0], centers[1])
        self.assertLess(centers[1], centers[2])
        self.assertGreater(centers[1] - centers[0], out["canvas"]["height"] * 0.2)
        self.assertGreater(metrics(task["source"], out)["min_font"], 30)

    def test_fresh_process_determinism(self):
        code = ("import hashlib,json; from pipelines import get_pipeline; "
                "t=json.load(open('tests/fixtures/typography.json')); "
                "o=get_pipeline('adaptive')(t['source'],t['target_canvas']); "
                "print(hashlib.sha256(json.dumps(o,sort_keys=True).encode()).hexdigest())")
        self.assertEqual(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT),
                         subprocess.check_output([sys.executable, "-c", code], cwd=ROOT))

    def test_independent_designs_schema_contract_and_feasible_copy(self):
        from jsonschema import Draft202012Validator
        schema = Draft202012Validator(json.loads((ROOT / "chameleon_design_schema_v0.9.json").read_text()))
        for task in fixtures():
            source, target = task["source"], task["target_canvas"]
            original, target_before = copy.deepcopy(source), target.copy()
            out, diagnostics = search(source, target)
            self.assertEqual(validate(source, target, out), [])
            self.assertEqual(list(schema.iter_errors(out)), [])
            q = metrics(source, out)
            self.assertEqual(q["text_overflows"], 0)
            self.assertEqual(q["overlap_pairs"], 0)
            self.assertGreater(q["min_font"], 10)
            self.assertGreater(diagnostics["evaluated"], 1)
            self.assertEqual(source, original)
            self.assertEqual(target, target_before)

    def test_overflowing_group_label_fits_without_scattering_group(self):
        source = fixtures()[0]["source"]
        source["elements"] = [e for e in source["elements"] if e.get("group_id")]
        source["elements"][1]["content"] = "Reserve every seat for our extraordinary botanical tasting evening"
        source["elements"][1]["font_size"] = 38
        target = {"width": 600, "height": 180}
        out = get_pipeline("adaptive")(source, target)
        self.assertEqual(validate(source, target, out), [])
        self.assertEqual(metrics(source, out)["text_overflows"], 0)
        self.assertEqual(out["elements"][1]["content"], source["elements"][1]["content"])
        self.assertGreater(out["elements"][1]["font_size"], 6)

    def test_invalid_candidate_cannot_win_by_score(self):
        task = fixtures()[0]
        source, target = task["source"], task["target_canvas"]
        valid = get_pipeline("anchored")(source, target)
        invalid = copy.deepcopy(valid)
        invalid["elements"][0]["asset_id"] = "invented.png"
        with patch("pipelines.adaptive.pipeline._candidates", return_value=iter([("bad", invalid), ("valid", valid)])):
            out, diagnostics = search(source, target)
        self.assertEqual(diagnostics["selected"], "valid")
        self.assertEqual(diagnostics["rejected"], 1)
        self.assertEqual(validate(source, target, out), [])

    def test_invalid_source_fails_explicitly(self):
        task = fixtures()[0]
        for mutation in ("duplicate", "nan", "zero_canvas"):
            source, target = copy.deepcopy(task["source"]), task["target_canvas"].copy()
            if mutation == "duplicate":
                source["elements"][1]["id"] = source["elements"][0]["id"]
            elif mutation == "nan":
                source["elements"][1]["rotation"] = float("nan")
            else:
                target["width"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                search(source, target)

    def test_renaming_reordering_and_task_order(self):
        task = fixtures()[1]
        source, target = task["source"], task["target_canvas"]
        expected = get_pipeline("adaptive")(source, target)
        renamed = dict(variants(source))["renamed"]
        renamed_out = get_pipeline("adaptive")(renamed, target)
        for a, b in zip(expected["elements"], renamed_out["elements"]):
            self.assertEqual([a.get(k) for k in ("x", "y", "width", "height", "font_size")],
                             [b.get(k) for k in ("x", "y", "width", "height", "font_size")])
        reordered = dict(source, elements=list(reversed(source["elements"])))
        actual = get_pipeline("adaptive")(reordered, target)
        self.assertEqual({e["id"]: e for e in expected["elements"]}, {e["id"]: e for e in actual["elements"]})
        get_pipeline("adaptive")(fixtures()[0]["source"], {"width": 500, "height": 500})
        self.assertEqual(get_pipeline("adaptive")(source, target), expected)

    def test_validator_rejects_detached_group_label(self):
        task = fixtures()[0]
        out = get_pipeline("anchored")(task["source"], task["target_canvas"])
        out["elements"][-1]["x"] += 10
        self.assertTrue(any("inconsistent geometry" in p for p in validate(task["source"], task["target_canvas"], out)))

    def test_metrics_match_by_id_when_output_is_reordered(self):
        task = fixtures()[0]
        out = get_pipeline("anchored")(task["source"], task["target_canvas"])
        expected = metrics(task["source"], out)
        out["elements"].reverse()
        actual = metrics(task["source"], out)
        self.assertEqual(expected["overlap_severity"], actual["overlap_severity"])
        self.assertEqual(expected["overlaps"], actual["overlaps"])


class EvaluationTests(unittest.TestCase):
    def test_nonfinite_pipeline_output_does_not_poison_report(self):
        def broken(source, target):
            out = get_pipeline("anchored")(source, target)
            out["elements"][0]["x"] = float("nan")
            return out

        with temp_dir() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                patch("scripts.run_matrix.get_pipeline", return_value=broken):
            code = matrix_main(["--input-dir", "tests/fixtures", "--output-dir", tmp,
                                "--pipelines", "hierarchy", "--targets", "leaderboard"])
            report = json.loads((Path(tmp) / "report.json").read_text())
            self.assertEqual(code, 1)
            self.assertTrue(all(r["problems"] for r in report["cases"]))
            self.assertTrue((Path(tmp) / "index.html").is_file())

    def test_readability_gate_fails_and_reports_why(self):
        with temp_dir() as tmp, contextlib.redirect_stdout(io.StringIO()):
            code = matrix_main(["--input-dir", "tests/fixtures", "--output-dir", tmp,
                                "--pipelines", "anchored", "--targets", "leaderboard",
                                "--schema", "--min-font", "100"])
            report = json.loads((Path(tmp) / "report.json").read_text())
            self.assertEqual(code, 1)
            self.assertTrue(report["schema_checked"])
            self.assertGreater(report["summary"]["anchored"]["quality_failures"], 0)
            self.assertTrue(any("font below" in p for r in report["cases"] for p in r["quality_problems"]))


if __name__ == "__main__":
    unittest.main()
