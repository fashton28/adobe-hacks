"""Round-2 regressions: backdrops, frames, followers, repeated sets and painted type.

Synthetic designs only; no sample ids, task names or fixture files are encoded.
Run with: python -m unittest discover -s tests -v
"""

import contextlib
import copy
import io
import json
import shutil
import unittest
import uuid
from pathlib import Path

from pipelines import get_pipeline
from pipelines.adaptive.pipeline import search
from pipelines.common.quality import BACKDROP_SLACK, EMPTY_GROWTH, canvas_fill, metrics
from pipelines.common.text import measure, paint_size, tight_width
from pipelines.common.units import build_units, ink_box
from pipelines.common.validate import validate
from scripts.run_matrix import main as matrix_main

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ({"width": 1500, "height": 500}, {"width": 728, "height": 90}, {"width": 1000, "height": 1500},
           {"width": 300, "height": 250})


@contextlib.contextmanager
def temp_dir():
    parent = ROOT / "output" / "test-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"round2-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        if path.resolve().parent != parent.resolve():
            raise RuntimeError("Temporary cleanup escaped the test directory")
        shutil.rmtree(path)


def text(eid, x, y, w, h, content, size, **extra):
    return {"id": eid, "type": "text", "x": x, "y": y, "width": w, "height": h, "content": content,
            "font_family": "Solstice Sans", "font_size": size, "color": "rgba(255,255,255,1)",
            "text_align": "center", **extra}


def rect(eid, x, y, w, h, fill="rgba(26,32,64,1)", **extra):
    return {"id": eid, "type": "shape", "shape_type": "rectangle", "x": x, "y": y, "width": w, "height": h,
            "fill_color": fill, **extra}


def design(backdrop):
    """A mostly empty canvas whose colour comes from one full-bleed shape."""
    return {"canvas": {"width": 1080, "height": 1350}, "elements": [
        backdrop,
        {"id": "disc", "type": "shape", "shape_type": "ellipse", "x": 240, "y": 300, "width": 600, "height": 600,
         "fill_color": "rgba(240,178,66,1)"},
        text("caption", 290, 1000, 500, 80, "A short caption under the disc", 30),
    ]}


class BackdropTests(unittest.TestCase):
    def check_backdrop(self, source):
        for target in TARGETS:
            with self.subTest(target=target):
                out = get_pipeline("adaptive")(source, target)
                self.assertEqual(validate(source, target, out), [])
                field = next(e for e in out["elements"] if e["id"] == source["elements"][0]["id"])
                self.assertEqual((field["x"], field["y"], field["width"], field["height"]),
                                 (0, 0, target["width"], target["height"]))
                q = metrics(source, out)
                self.assertLessEqual(q["backdrop_shortfall"], BACKDROP_SLACK)
                self.assertLessEqual(q["empty_output"] - q["empty_source"], EMPTY_GROWTH)
                self.assertEqual((q["text_overflows"], q["overlap_pairs"]), (0, 0))

    def test_solid_full_canvas_shape_stretches(self):
        self.check_backdrop(design(rect("field", 0, 0, 1080, 1350)))

    def test_translucent_scrim_stretches(self):
        self.check_backdrop(design(rect("scrim", 0, 0, 1080, 1350, fill="rgba(20,16,40,0.45)")))

    def test_near_full_bleed_paper_sheet_stretches(self):
        self.check_backdrop(design(rect("sheet", 20, 20, 1040, 1310, fill="rgba(248,243,234,1)")))

    def test_rotated_or_grouped_large_shapes_are_not_backdrops(self):
        rotated = design(rect("field", 0, 0, 1080, 1350, rotation=5))
        grouped = design(rect("field", 0, 0, 1080, 1350, group_id="g"))
        for source in (rotated, grouped):
            self.assertNotEqual(build_units(source)[0]["kind"], "bg")

    def test_metric_flags_a_backdrop_shrunk_into_a_box(self):
        source = design(rect("field", 0, 0, 1080, 1350))
        target = {"width": 1500, "height": 500}
        out = get_pipeline("adaptive")(source, target)
        broken = copy.deepcopy(out)
        field = broken["elements"][0]
        field.update(x=10, y=10, width=380, height=475)  # the round-1 failure: a floating box
        fill = canvas_fill(source, broken)
        self.assertGreater(fill["backdrop_shortfall"], BACKDROP_SLACK)
        self.assertGreater(fill["empty_output"] - fill["empty_source"], EMPTY_GROWTH)
        self.assertEqual(validate(source, target, broken), [])  # structurally valid, visually broken

    def test_strict_matrix_fails_a_lost_backdrop(self):
        source = design(rect("field", 0, 0, 1080, 1350))

        def shrink(src, target):
            out = get_pipeline("anchored")(src, target)
            out["elements"][0].update(x=0, y=0, width=target["width"] / 4, height=target["height"])
            return out

        with temp_dir() as tmp:
            (tmp / "in").mkdir()
            (tmp / "in" / "task.json").write_text(json.dumps({"source": source,
                                                              "target_canvas": {"width": 1500, "height": 500}}))
            from unittest.mock import patch
            with patch("scripts.run_matrix.get_pipeline", return_value=shrink), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = matrix_main(["--input-dir", str(tmp / "in"), "--output-dir", str(tmp / "out"),
                                    "--pipelines", "anchored", "--targets", "leaderboard", "--strict-quality"])
            report = json.loads((tmp / "out" / "report.json").read_text())
        self.assertEqual(code, 1)
        problems = [p for case in report["cases"] for p in case["quality_problems"]]
        self.assertTrue(any("backdrop covers" in p for p in problems), problems)


class FrameAndFollowerTests(unittest.TestCase):
    def sheet_design(self):
        return {"canvas": {"width": 1000, "height": 1000}, "elements": [
            rect("field", 0, 0, 1000, 1000),
            rect("card", 100, 100, 800, 800, fill="rgba(250,246,238,1)", corner_radius=24),
            text("title", 160, 160, 680, 120, "Inset sheet keeps its copy", 52, color="rgba(30,30,30,1)"),
            text("body", 160, 300, 680, 120, "Every line stays on the paper sheet.", 24, color="rgba(60,60,60,1)"),
            {"id": "art", "type": "image", "asset_id": "solstice_bottle.png", "fit": "contain",
             "x": 350, "y": 440, "width": 300, "height": 300},
            rect("band", 0, 960, 1000, 40, fill="rgba(232,106,58,1)"),
        ]}

    def test_inset_sheet_maps_to_region_and_holds_the_copy(self):
        source = self.sheet_design()
        kinds = {source["elements"][u["idx"][0]]["id"]: u["kind"] for u in build_units(source)}
        self.assertEqual((kinds["field"], kinds["card"], kinds["band"]), ("bg", "panel", "panel"))
        for target in TARGETS:
            with self.subTest(target=target):
                out = get_pipeline("adaptive")(source, target)
                self.assertEqual(validate(source, target, out), [])
                by_id = {e["id"]: e for e in out["elements"]}
                card, band = by_id["card"], by_id["band"]
                # The sheet keeps its relative margins; the band still spans the bottom edge.
                self.assertAlmostEqual(card["x"], 0.1 * target["width"])
                self.assertAlmostEqual(card["width"], 0.8 * target["width"])
                self.assertAlmostEqual(band["width"], target["width"])
                self.assertAlmostEqual(band["y"] + band["height"], target["height"])
                for eid in ("title", "body", "art"):
                    x0, y0, x1, y1 = ink_box(by_id[eid])
                    self.assertGreaterEqual(x0, card["x"] - 0.5)
                    self.assertLessEqual(x1, card["x"] + card["width"] + 0.5)
                    self.assertGreaterEqual(y0, card["y"] - 0.5)
                    self.assertLessEqual(y1, min(card["y"] + card["height"], band["y"]) + 0.5)

    def test_glow_follows_the_unit_it_surrounds(self):
        source = {"canvas": {"width": 1080, "height": 1080}, "elements": [
            rect("field", 0, 0, 1080, 1080),
            {"id": "glow", "type": "shape", "shape_type": "ellipse", "x": 240, "y": 120, "width": 700, "height": 700,
             "fill_color": "rgba(255,255,255,1)", "opacity": 0.1},
            {"id": "art", "type": "image", "asset_id": "solstice_bottle.png", "fit": "contain",
             "x": 340, "y": 200, "width": 520, "height": 520},
            text("title", 90, 860, 900, 120, "Glow stays behind the product", 64),
        ]}
        for target in TARGETS:
            with self.subTest(target=target):
                out = get_pipeline("adaptive")(source, target)
                by_id = {e["id"]: e for e in out["elements"]}
                glow, art = by_id["glow"], by_id["art"]
                gx, gy = glow["x"] + glow["width"] / 2, glow["y"] + glow["height"] / 2
                ax, ay = art["x"] + art["width"] / 2, art["y"] + art["height"] / 2
                # Same relative offset as the source (centres 70 and 0 apart), within clamping.
                self.assertLess(abs(gx - ax), 0.25 * art["width"] + 1)
                self.assertLess(abs(gy - ay), 0.25 * art["height"] + 1)

    def test_tinted_divider_line_stays_structural(self):
        source = design(rect("field", 0, 0, 1080, 1350))
        source["elements"].append({"id": "rule", "type": "shape", "shape_type": "line", "x": 80, "y": 960,
                                   "width": 920, "height": 4, "fill_color": "rgba(255,255,255,0.7)"})
        kinds = {source["elements"][u["idx"][0]]["id"]: u["kind"] for u in build_units(source)}
        self.assertEqual(kinds["rule"], "rigid")
        out = get_pipeline("adaptive")(source, {"width": 1500, "height": 500})
        self.assertEqual(metrics(source, out)["overlap_pairs"], 0)


class RepeatedSetTests(unittest.TestCase):
    def cards(self):
        elements = [{"id": "bg", "type": "image", "asset_id": "solstice_bg_gradient.png", "fit": "cover",
                     "x": 0, "y": 0, "width": 1280, "height": 720},
                    text("title", 340, 40, 600, 70, "Three cards", 48)]
        for i in range(3):
            x = 130 + i * 360
            elements += [
                {"id": f"art{i}", "type": "image", "asset_id": "solstice_bottle.png", "fit": "contain",
                 "x": x, "y": 150, "width": 300, "height": 300, "group_id": f"card{i}"},
                text(f"name{i}", x - 30, 466, 360, 40, f"Flavor {i}", 26, group_id=f"card{i}"),
            ]
        return {"canvas": {"width": 1280, "height": 720}, "elements": elements}

    def test_cards_form_one_set_and_stay_even(self):
        source = self.cards()
        sets = {u.get("set") for u in build_units(source) if len(u["idx"]) == 2}
        self.assertEqual(len(sets), 1)
        self.assertIsNotNone(sets.pop())
        for target in ({"width": 1080, "height": 1920}, {"width": 1080, "height": 1080},
                       {"width": 1600, "height": 400}, {"width": 728, "height": 90}):
            with self.subTest(target=target):
                out = get_pipeline("adaptive")(source, target)
                self.assertEqual(validate(source, target, out), [])
                arts = [e for e in out["elements"] if e["id"].startswith("art")]
                self.assertAlmostEqual(min(a["width"] for a in arts), max(a["width"] for a in arts), places=6)
                tops = sorted({round(a["y"], 3) for a in arts})
                lefts = sorted({round(a["x"], 3) for a in arts})
                # One row of three or one column of three: never a 2 + 1 split.
                self.assertTrue(len(tops) == 1 or len(lefts) == 1, (tops, lefts))


class PaintedTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from renderer.converter.brand_fonts import load_brand_font_manager
        cls.fonts = load_brand_font_manager(str(ROOT / "brand_kit/fonts"))

    def test_every_pipeline_font_size_is_an_integer(self):
        tasks = [json.loads(p.read_text()) for p in sorted((ROOT / "input").glob("*.json"))]
        for task in tasks:
            for target in TARGETS:
                out = get_pipeline("adaptive")(task["source"], target)
                for el in out["elements"]:
                    if el["type"] == "text":
                        self.assertEqual(el["font_size"], paint_size(el["font_size"]))
                        self.assertIsInstance(el["font_size"], int)

    def converted(self, el):
        from renderer.converter.convert import convert_chameleon_to_crello
        doc = {"canvas": {"width": 2000, "height": 2000}, "elements": [el]}
        return convert_chameleon_to_crello(doc, self.fonts)[0]

    def painted_widths(self, el, converted):
        """Line widths the way cr-renderer paints them: per style span, spacing inside spans."""
        import skia

        wrapped, size = converted["text"][0], int(el["font_size"])
        result, offset = [], 0
        for line in wrapped.split("\n"):
            spans, current, key = [], "", None
            for i, char in enumerate(line):
                k = offset + i
                style = (converted["font_bold"][0][k], converted["font_italic"][0][k], converted["text_color"][0][k])
                if key is not None and style != key:
                    spans.append((key, current))
                    current = ""
                key, current = style, current + char
            if current:
                spans.append((key, current))
            total = 0.0
            for (bold, italic, _), chunk in spans:
                weight = "bold" if bold else "regular"
                style = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
                font = skia.Font(skia.Typeface.MakeFromData(self.fonts.lookup(el["font_family"], weight, style)), size)
                glyphs = font.textToGlyphs(chunk)
                total += sum(font.getWidths(glyphs)) + el.get("letter_spacing", 0) * max(0, len(glyphs) - 1)
            result.append(total)
            offset += len(line) + 1
        return result

    def test_measure_matches_renderer_spans_with_colour_runs_and_spacing(self):
        el = text("t", 0, 0, 260, 400, "Golden hour, bottled slowly for long summer evenings with friends", 17,
                  letter_spacing=1.5, style_runs=[{"start": 7, "end": 12, "color": "rgba(240,178,66,1)"},
                                                  {"start": 20, "end": 27, "font_weight": "bold"}])
        for width in (90, 160, 260, 600):
            with self.subTest(width=width):
                el["width"] = width
                converted = self.converted(el)
                lines, widest = measure(el, el["font_size"], width)
                self.assertEqual(lines, converted["text"][0].count("\n") + 1)
                self.assertAlmostEqual(widest, max(self.painted_widths(el, converted)), places=4)

    def test_tight_width_keeps_converter_wrapping(self):
        contents = ("Small-batch botanical infusions blended with wild honey and blood orange zest",
                    "Été éternel : l'élixir du solstice, kühl servieren und langsam genießen",
                    "Short", "Two\nlines with a manual break inside them")
        for content in contents:
            for size in (7, 13, 24):
                for width in (60, 180, 420):
                    with self.subTest(content=content[:12], size=size, width=width):
                        el = text("t", 0, 0, width, 500, content, size)
                        before = self.converted(el)["text"][0]
                        el["width"] = tight_width(el, size, width)
                        self.assertLessEqual(el["width"], width)
                        self.assertEqual(self.converted(el)["text"][0], before)

    def test_text_ink_hugs_painted_lines(self):
        el = text("t", 100, 50, 600, 200, "Centered words", 30)
        x0, y0, x1, y1 = ink_box(el)
        _, widest = measure(el, 30, 600)
        self.assertAlmostEqual(x1 - x0, widest)
        self.assertAlmostEqual((x0 + x1) / 2, 400)
        self.assertEqual((y0, y1), (50, 50 + 30 * 1.2))


class SpeedTests(unittest.TestCase):
    def test_public_samples_search_quickly(self):
        import time
        for path in sorted((ROOT / "input").glob("*.json")):
            task = json.loads(path.read_text())
            started = time.perf_counter()
            search(task["source"], task["target_canvas"])
            # Generous bound for slow CI hosts; the container takes about 2s for the slowest sample.
            self.assertLess(time.perf_counter() - started, 15, path.name)


if __name__ == "__main__":
    unittest.main()
