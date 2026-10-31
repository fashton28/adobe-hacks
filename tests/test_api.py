"""Contract of the importable pipelines.api.run entry point used by the web viewer."""

import copy
import json
import unittest
from pathlib import Path

from pipelines import get_pipeline
from pipelines.api import run

ROOT = Path(__file__).resolve().parents[1]
KEYS = {"output", "validation", "metrics", "score", "pipeline", "elapsed_ms"}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.task = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())

    def test_run_returns_stable_keys_and_valid_serializable_result(self):
        source, target = self.task["source"], self.task["target_canvas"]
        original, target_before = copy.deepcopy(source), copy.deepcopy(target)
        result = run(source, target)
        self.assertEqual(set(result), KEYS)
        self.assertEqual(result["pipeline"], "adaptive")
        self.assertEqual(result["validation"], [])
        self.assertEqual(result["output"]["canvas"], target)
        self.assertEqual(result["output"], get_pipeline("adaptive")(source, target))
        self.assertIsInstance(result["score"], float)
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertEqual(result["metrics"]["text_overflows"], 0)
        json.dumps(result, allow_nan=False)
        self.assertEqual((source, target), (original, target_before))

    def test_run_selects_named_pipeline_and_rejects_unknown(self):
        result = run(self.task["source"], {"width": 300, "height": 250}, pipeline="anchored")
        self.assertEqual(result["pipeline"], "anchored")
        self.assertEqual(result["validation"], [])
        with self.assertRaises(ValueError):
            run(self.task["source"], {"width": 300, "height": 250}, pipeline="nope")

    def test_run_rejects_invalid_target(self):
        with self.assertRaises(ValueError):
            run(self.task["source"], {"width": 0, "height": 90})


if __name__ == "__main__":
    unittest.main()
