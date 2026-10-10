"""Contract, robustness and renderer regression tests. No test-only dependencies.

Run with: python -m unittest discover -s tests -v
"""

import copy
from contextlib import contextmanager
import json
import math
import subprocess
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

from pipelines import get_pipeline
from pipelines.common.quality import metrics
from pipelines.common.text import fit_text, measure
from pipelines.common.validate import is_background, validate
from scripts.run_matrix import TARGETS, main as matrix_main, variants

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def temp_dir():
    # mkdtemp's owner-only Windows ACL excludes the managed sandbox identity.
    # Normal mkdir inherits the workspace's writable ACL instead.
    parent = ROOT / "output" / "test-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"case-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        if path.resolve().parent != parent.resolve():
            raise RuntimeError("Temporary cleanup escaped the test directory")
        shutil.rmtree(path)


def samples():
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((ROOT / "input").glob("*.json"))]


def fixture():
    """Independent geometry, mixed typography and five groups; no sample roles."""
    elements = [
        {"id": "art", "type": "image", "x": 20, "y": 20, "width": 120, "height": 100,
         "asset_id": "unavailable.png", "fit": "contain"},
        {"id": "title", "type": "text", "x": 160, "y": 30, "width": 410, "height": 90,
         "content": "A different design", "font_family": "Solstice Serif", "font_size": 32,
         "font_weight": "bold", "color": "rgba(255,255,255,1)"},
        {"id": "body", "type": "text", "x": 25, "y": 160, "width": 550, "height": 60,
         "content": "Full copy stays intact.\nEven existing line breaks stay intact.",
         "font_family": "Solstice Sans", "font_size": 17, "letter_spacing": 0.4,
         "color": "rgba(255,255,255,1)", "style_runs": [{"start": 5, "end": 9, "font_weight": "bold"}]},
    ]
    for i in range(5):
        x, y = 20 + (i % 3) * 180, 250 + (i // 3) * 65
        elements += [
            {"id": f"box-{i}", "type": "shape", "x": x, "y": y, "width": 160, "height": 48,
             "shape_type": "rectangle", "fill_color": "rgba(220,60,50,1)", "group_id": f"g-{i}"},
            {"id": f"label-{i}", "type": "text", "x": x + 8, "y": y + 12, "width": 144, "height": 24,
             "content": f"Choice {i + 1}", "font_family": "Solstice Sans", "font_size": 14,
             "color": "rgba(255,255,255,1)", "group_id": f"g-{i}"},
        ]
    return {"canvas": {"width": 600, "height": 420}, "elements": elements}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.source = samples()[1]["source"]
        self.target = {"width": 728, "height": 90}
        self.out = get_pipeline("anchored")(self.source, self.target)

    def test_validator_rejects_missing_fields_and_malformed_output(self):
        self.assertTrue(validate(self.source, self.target, {}))
        self.out["elements"][0].pop("width")
        self.assertTrue(any("missing" in p for p in validate(self.source, self.target, self.out)))

    def test_validator_detects_duplicate_ids(self):
        self.out["elements"].append(copy.deepcopy(self.out["elements"][0]))
        self.assertIn("element ids differ from source", validate(self.source, self.target, self.out))

    def test_validator_rejects_preserved_property_changes(self):
        for field, value in [("asset_id", "replacement.png"), ("type", "shape"), ("opacity", 0), ("fit", "fill")]:
            with self.subTest(field=field):
                out = copy.deepcopy(self.out)
                out["elements"][0][field] = value
                self.assertTrue(validate(self.source, self.target, out))
        text = next(e for e in self.out["elements"] if e["type"] == "text")
        text["style_runs"] = [{"start": 0, "end": 1, "color": "red"}]
        self.assertTrue(validate(self.source, self.target, self.out))

    def test_validator_rejects_nonfinite_rotation_and_collapsed_images(self):
        for field, value in [("rotation", float("nan")), ("x", float("inf")), ("height", 0)]:
            with self.subTest(field=field):
                out = copy.deepcopy(self.out)
                out["elements"][0][field] = value
                self.assertTrue(validate(self.source, self.target, out))

    def test_large_foreground_cannot_bypass_ratio_check(self):
        el = {"id": "image", "type": "image", "asset_id": "image.png", "fit": "contain",
              "x": 0, "y": 0, "width": 600, "height": 420}
        source = {"canvas": {"width": 600, "height": 420}, "elements": [el]}
        self.assertFalse(is_background(el, source["canvas"]))
        out = {"canvas": self.target, "elements": [dict(el, width=728, height=90)]}
        self.assertTrue(any("aspect ratio" in p for p in validate(source, self.target, out)))

    def test_cover_background_fills_canvas(self):
        bg = self.out["elements"][0]
        self.assertEqual((bg["x"], bg["y"], bg["width"], bg["height"]), (0, 0, 728, 90))
        self.assertEqual(validate(self.source, self.target, self.out), [])

    def test_anchored_repairs_rotated_source_bleed(self):
        source = samples()[2]["source"]
        out = get_pipeline("anchored")(source, source["canvas"])
        self.assertEqual(validate(source, source["canvas"], out), [])
        ribbon = [e for e in out["elements"] if e.get("group_id") == "ribbon"]
        original = [e for e in source["elements"] if e.get("group_id") == "ribbon"]
        self.assertAlmostEqual(ribbon[1]["y"] - ribbon[0]["y"], original[1]["y"] - original[0]["y"])


class LayoutTests(unittest.TestCase):
    def test_public_matrix_contract_and_text_fit(self):
        for task in samples():
            source = task["source"]
            original = copy.deepcopy(source)
            for name in ("hierarchy", "flow"):
                for target_name, (w, h) in TARGETS.items():
                    with self.subTest(task=task["task_id"], pipeline=name, target=target_name):
                        target = {"width": w, "height": h}
                        out = get_pipeline(name)(source, target)
                        self.assertEqual(validate(source, target, out), [])
                        q = metrics(source, out)
                        self.assertEqual(q["text_overflows"], 0)
                        self.assertEqual(q["overlap_pairs"], 0)
                        self.assertEqual(source, original)

    def test_banner_readability_improves_over_previous_pipeline(self):
        task = samples()[2]
        source, target = task["source"], task["target_canvas"]
        before = metrics(source, get_pipeline("layout_v1")(source, target))
        after = metrics(source, get_pipeline("flow")(source, target))
        self.assertGreater(after["min_font"], before["min_font"] * 1.5)
        self.assertLess(after["below_6px"], before["below_6px"])

    def test_renaming_and_removing_notes_preserves_decisions(self):
        source = fixture()
        renamed = dict(variants(source))["renamed"]
        target = {"width": 700, "height": 150}
        a, b = (get_pipeline("flow")(s, target) for s in (source, renamed))
        for first, second in zip(a["elements"], b["elements"]):
            for field in ("x", "y", "width", "height", "font_size"):
                self.assertEqual(first.get(field), second.get(field))

    def test_reordering_elements_and_repeated_calls_are_deterministic(self):
        source = fixture()
        target = {"width": 360, "height": 250}
        expected = get_pipeline("flow")(source, target)
        shuffled = copy.deepcopy(source)
        shuffled["elements"].reverse()
        actual = get_pipeline("flow")(shuffled, target)
        self.assertEqual({e["id"]: e for e in expected["elements"]}, {e["id"]: e for e in actual["elements"]})
        get_pipeline("flow")(source, {"width": 160, "height": 600})
        self.assertEqual(get_pipeline("flow")(source, target), expected)

    def test_foreground_missing_asset_and_group_transforms_preserved(self):
        source = fixture()
        target = {"width": 700, "height": 160}
        out = get_pipeline("flow")(source, target)
        self.assertEqual(validate(source, target, out), [])
        self.assertEqual(metrics(source, out)["text_overflows"], 0)
        art = out["elements"][0]
        self.assertEqual(art["asset_id"], "unavailable.png")
        self.assertAlmostEqual(art["width"] / art["height"], 1.2)
        for i in range(5):
            original = [e for e in source["elements"] if e.get("group_id") == f"g-{i}"]
            group = [e for e in out["elements"] if e.get("group_id") == f"g-{i}"]
            scale = group[0]["width"] / original[0]["width"]
            self.assertAlmostEqual(group[1]["x"] - group[0]["x"], 8 * scale)
            self.assertAlmostEqual(group[1]["y"] - group[0]["y"], 12 * scale)
            self.assertAlmostEqual(group[1]["font_size"], 14 * scale)

    def test_rotated_groups_and_missing_roles(self):
        source = dict(variants(fixture()))["rotated_groups"]
        for name in ("anchored", "hierarchy", "flow"):
            for elements in (source["elements"], [source["elements"][1]], [source["elements"][0]]):
                design = dict(source, elements=elements)
                target = {"width": 240, "height": 180}
                out = get_pipeline(name)(design, target)
                self.assertEqual(validate(design, target, out), [])

    def test_rotated_single_text_bounds(self):
        source = fixture()
        source["elements"] = [dict(source["elements"][1], rotation=45)]
        target = {"width": 200, "height": 100}
        out = get_pipeline("flow")(source, target)
        self.assertEqual(validate(source, target, out), [])
        el = out["elements"][0]
        # Independently calculate all four rotated corners.
        angle = math.radians(45)
        for dx in (-el["width"] / 2, el["width"] / 2):
            for dy in (-el["height"] / 2, el["height"] / 2):
                x = el["x"] + el["width"] / 2 + dx * math.cos(angle) - dy * math.sin(angle)
                y = el["y"] + el["height"] / 2 + dx * math.sin(angle) + dy * math.cos(angle)
                self.assertGreaterEqual(x, -0.5)
                self.assertLessEqual(x, 200.5)
                self.assertGreaterEqual(y, -0.5)
                self.assertLessEqual(y, 100.5)


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from renderer.converter.brand_fonts import load_brand_font_manager
        cls.fonts = load_brand_font_manager(str(ROOT / "brand_kit/fonts"))

    def test_measured_wrap_matches_converter_including_spacing_and_runs(self):
        import skia
        from renderer.converter.convert import convert_chameleon_to_crello
        for width in (70, 150, 500):
            el = fixture()["elements"][2]
            el.update(width=width, font_size=17.5)
            doc = {"canvas": {"width": 600, "height": 420}, "elements": [el]}
            converted, _ = convert_chameleon_to_crello(doc, self.fonts)
            wrapped = converted["text"][0]
            lines, widest = measure(el, el["font_size"], width)
            self.assertEqual(lines, wrapped.count("\n") + 1)
            # Compute painted widths directly from the actual font lookup,
            # independently of the layout helper and its caches.
            widths, current, count = [], 0, 0
            for i, char in enumerate(wrapped):
                if char == "\n":
                    widths.append(current)
                    current, count = 0, 0
                    continue
                bold = converted["font_bold"][0][i]
                data = self.fonts.lookup(el["font_family"], "bold" if bold else "regular", "bold" if bold else "regular")
                font = skia.Font(skia.Typeface.MakeFromData(data), int(el["font_size"]))
                current += font.getWidths(font.textToGlyphs(char))[0] + (el["letter_spacing"] if count else 0)
                count += 1
            widths.append(current)
            self.assertAlmostEqual(widest, max(widths))

    def test_unbreakable_word_and_scaled_spacing_fit(self):
        el = fixture()["elements"][2]
        el.update(content="VeryLongUnbreakableWord", letter_spacing=2)
        size, h = fit_text(el, 150, 60, 20)
        placed = dict(el, font_size=size, letter_spacing=2 * size / el["font_size"])
        lines, widest = measure(placed, size, 150)
        self.assertLessEqual(widest, 150.001)
        self.assertLessEqual(h, 60)
        self.assertEqual(lines, 1)

    def test_real_render_and_missing_asset_warning(self):
        from PIL import Image
        from renderer.converter.convert import render_design_to_png
        task = samples()[2]
        out = get_pipeline("flow")(task["source"], task["target_canvas"])
        with temp_dir() as tmp:
            path = Path(tmp) / "preview.png"
            warnings = render_design_to_png(out, ROOT / "brand_kit/assets", path)
            self.assertTrue(any("solstice_holiday_badge_2025.png" in w for w in warnings))
            with Image.open(path) as png:
                self.assertEqual(png.size, (728, 90))
                self.assertGreater(len(png.getcolors(maxcolors=1_000_000)), 100)


class RunnerTests(unittest.TestCase):
    def test_empty_input_fails_instead_of_false_success(self):
        with temp_dir() as tmp:
            with self.assertRaises(SystemExit) as caught:
                matrix_main(["--input-dir", tmp])
            self.assertEqual(caught.exception.code, 2)

    def test_fresh_process_output_is_deterministic(self):
        code = ("import hashlib,json; from pipelines import get_pipeline; "
                "s=json.load(open('input/chameleon_sample_level3_advanced.json'))['source']; "
                "o=get_pipeline('flow')(s,{'width':728,'height':90}); "
                "print(hashlib.sha256(json.dumps(o,sort_keys=True).encode()).hexdigest())")
        a = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT)
        b = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT)
        self.assertEqual(a, b)

    def test_runner_records_errors_and_isolates_mutating_pipeline(self):
        source = fixture()

        def failing(src, target):
            src["elements"][0]["asset_id"] = "changed.png"
            target["width"] = 999
            raise RuntimeError("intentional failure")

        def succeeding(src, target):
            self.assertEqual(src, source)
            self.assertEqual(target, {"width": 300, "height": 250})
            return get_pipeline("anchored")(src, target)

        with temp_dir() as tmp:
            root = Path(tmp)
            (root / "fixture.json").write_text(json.dumps({"source": source}), encoding="utf-8")
            with patch("scripts.run_matrix.get_pipeline", side_effect=lambda name: failing if name == "hierarchy" else succeeding):
                code = matrix_main(["--input-dir", str(root), "--output-dir", str(root / "report"),
                                    "--pipelines", "hierarchy", "anchored", "--targets", "medium_rect"])
            report = json.loads((root / "report/report.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertIn("intentional failure", report["cases"][0]["problems"][0])
            self.assertEqual(report["cases"][1]["problems"], [])


if __name__ == "__main__":
    unittest.main()
