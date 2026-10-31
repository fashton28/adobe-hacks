"""Regressions for crash-prone geometry and both on-canvas definitions."""

import unittest
from unittest.mock import patch

from pipelines import PIPELINES, get_pipeline
from pipelines.adaptive.pipeline import search
from pipelines.common.units import build_units, panel_box
from pipelines.common.validate import validate


def _text(id_, x, y, w, h, size, content="Summer light in every can", **extra):
    return {"id": id_, "type": "text", "x": x, "y": y, "width": w, "height": h, "z_index": 2,
            "content": content, "font_family": "Solstice Sans", "font_size": size,
            "color": "#ffffff", **extra}


def _band(id_, x, y, w, h):
    return {"id": id_, "type": "shape", "shape_type": "rectangle", "x": x, "y": y, "width": w,
            "height": h, "z_index": 1, "fill_color": "rgba(30,30,30,1)"}


def _source(*elements):
    bg = {"id": "bg", "type": "shape", "shape_type": "rectangle", "x": 0, "y": 0, "width": 1080,
          "height": 1080, "z_index": 0, "fill_color": "rgba(40,20,60,1)"}
    return {"canvas": {"width": 1080, "height": 1080}, "elements": [bg, *elements]}


def unrotated_off_canvas(out):
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    return [e["id"] for e in out["elements"]
            if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > W + 0.5 or e["y"] + e["height"] > H + 0.5]


class RobustnessTests(unittest.TestCase):
    def test_band_outside_the_source_canvas_keeps_a_nonnegative_box(self):
        for band in (_band("band", -20, 0, 10, 1080), _band("band", 1085, 0, 10, 1080),
                     _band("band", 0, -30, 1080, 12), _band("band", 0, 1100, 1080, 12)):
            source = _source(_text("t", 100, 400, 800, 120, 48), band)
            unit = next(u for u in build_units(source) if source["elements"][u["idx"][0]]["id"] == "band")
            x0, y0, x1, y1 = panel_box(source, unit, 1080, 1920)
            self.assertGreaterEqual(x1 - x0, 0)
            self.assertGreaterEqual(y1 - y0, 0)
            target = {"width": 1080, "height": 1920}
            out, info = search(source, target)
            self.assertTrue(info["valid"], info)
            self.assertEqual(validate(source, target, out), [])

    def test_search_returns_a_design_when_no_candidate_is_valid(self):
        source = _source(_text("t", 100, 400, 800, 120, 48))
        target = {"width": 600, "height": 600}
        with patch("pipelines.adaptive.pipeline.validate", return_value=["forced"]):
            out, info = search(source, target)
        self.assertFalse(info["valid"])
        self.assertEqual({e["id"] for e in out["elements"]}, {"bg", "t"})

    def test_zero_line_height_is_accepted(self):
        source = _source(_text("t", 100, 400, 800, 120, 48, line_height=0))
        target = {"width": 728, "height": 90}
        _, info = search(source, target)
        self.assertTrue(info["valid"], info)

    def test_rotated_element_keeps_its_unrotated_box_on_canvas(self):
        side = _text("side", 600, 500, 800, 60, 40, content="VERTICAL SIDE LABEL TEXT", rotation=90)
        source = _source(_text("title", 80, 80, 500, 120, 56, content="Title copy"), side)
        for target in ({"width": 160, "height": 600}, {"width": 1080, "height": 1920},
                       {"width": 728, "height": 90}, {"width": 1080, "height": 1080}):
            for name in ("anchored", "adaptive", "flow"):
                if name not in PIPELINES:
                    continue
                out = get_pipeline(name)(source, target)
                self.assertEqual(validate(source, target, out), [], (name, target))
                self.assertEqual(unrotated_off_canvas(out), [], (name, target))

    def test_validate_reports_an_unrotated_box_off_canvas(self):
        source = _source(_text("side", 100, 500, 800, 60, 40, rotation=90))
        target = {"width": 200, "height": 1080}
        out = {"canvas": dict(target), "elements": [dict(e) for e in source["elements"]]}
        out["elements"][0].update(width=200)
        side = out["elements"][1]
        # Rotated bounds (60 x 800) fit; the unrotated 800 x 60 box does not.
        side.update(x=100 - 400 + 30, y=140)
        self.assertTrue(any("side: off-canvas" in p for p in validate(source, target, out)))


if __name__ == "__main__":
    unittest.main()
