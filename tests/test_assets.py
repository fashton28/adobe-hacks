"""Asset fidelity, official missing-asset placeholders and product visibility regressions.

These tests pin the behavior of the OFFICIAL, unmodified starter renderer
(the one judges use): a missing asset is painted as a visible, labeled,
opaque placeholder box, and contain-fit pastes RGBA art using its own alpha
as the mask. Our engine has to live with both, so the tests document them.
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image

from pipelines import get_pipeline
from pipelines.common.assets import asset_info
from pipelines.common.geometry import aabb, overlap_area
from pipelines.common.placeholders import place_missing_assets
from pipelines.common.quality import metrics
from pipelines.common.validate import validate
from renderer.converter.assets import _fit_image, load_asset_image
from renderer.converter.brand_fonts import load_brand_font_manager
from renderer.converter.convert import convert_chameleon_to_crello

ROOT = Path(__file__).resolve().parents[1]
MISSING = "solstice_holiday_badge_2025.png"


class AssetTests(unittest.TestCase):
    def test_contain_keeps_opaque_and_transparent_pixels_and_never_mutates_input(self):
        source = Image.new("RGBA", (4, 1))
        source.putdata([(255, 255, 255, a) for a in (0, 64, 128, 255)])
        original = source.tobytes()
        fitted = _fit_image(source, 4, 1, "contain")
        self.assertEqual(fitted.size, (4, 1))
        self.assertEqual(source.tobytes(), original)
        pixels = [fitted.getpixel((x, 0)) for x in range(4)]
        self.assertEqual(pixels[0][3], 0)
        self.assertEqual(pixels[3], (255, 255, 255, 255))
        # The official paste uses the art's own alpha as the mask, so
        # semi-transparent edges are attenuated but never become more opaque.
        for (_, _, _, alpha), expected in zip(pixels[1:3], (64, 128)):
            self.assertLessEqual(alpha, expected)

    def test_missing_asset_paints_visible_opaque_placeholder(self):
        assets = str(ROOT / "brand_kit/assets")
        self.assertFalse((ROOT / "brand_kit/assets" / MISSING).exists())
        image = load_asset_image(assets, MISSING, 120, 50)
        self.assertEqual(image.size, (120, 50))
        self.assertEqual(image.getchannel("A").getextrema(), (255, 255))

    def test_converter_retains_missing_element_with_warning_and_placeholder(self):
        source = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())["source"]
        element = next(e for e in source["elements"] if e["type"] == "image" and not asset_info(e["asset_id"])["available"])
        design = dict(source, elements=[element])
        original = copy.deepcopy(design)
        fonts = load_brand_font_manager(str(ROOT / "brand_kit/fonts"))
        example, warnings = convert_chameleon_to_crello(design, fonts, str(ROOT / "brand_kit/assets"))
        self.assertEqual(example["length"], 1)
        self.assertEqual(design, original)
        self.assertTrue(any(element["asset_id"] in w and "placeholder" in w for w in warnings))
        self.assertEqual(example["image"][0].getchannel("A").getextrema(), (255, 255))

    def test_wide_banner_keeps_product_detail_and_missing_identity(self):
        source = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())["source"]
        target = {"width": 1600, "height": 400}
        paths = sorted((ROOT / "brand_kit/assets").glob("*.png"))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        original = copy.deepcopy(source)
        out = get_pipeline("adaptive")(source, target)
        self.assertEqual(validate(source, target, out), [])
        q = metrics(source, out)
        self.assertEqual((q["text_overflows"], q["overlap_pairs"]), (0, 0))
        # Every copy stays legible (the 12px legal line is tertiary and may
        # yield a little to margins and hierarchy, never below 10px).
        self.assertGreaterEqual(q["min_font"], 10)
        product = next(e for e in out["elements"] if e["id"] == "product")
        self.assertGreater(product["width"], 280)
        visible = next(im for im in q["images"] if im["id"] == product["id"])
        self.assertGreater(visible["visible_width"], 120)
        self.assertIn("solstice_holiday_badge_2025.png", q["missing_assets"])
        self.assertEqual(product["asset_id"], "solstice_bottle.png")
        self.assertEqual({e["id"] for e in out["elements"]}, {e["id"] for e in source["elements"]})
        missing = next(e for e in out["elements"] if e["id"] == "holiday_watermark")
        self.assertEqual(missing["asset_id"], "solstice_holiday_badge_2025.png")
        self.assertGreater(missing["width"], 0)
        self.assertEqual(source, original)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


    def test_missing_placeholder_stays_clear_of_copy_at_every_target(self):
        task = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())
        source = task["source"]
        src = next(e for e in source["elements"] if e["id"] == "holiday_watermark")
        for target in ({"width": 1080, "height": 1350}, {"width": 1080, "height": 1920},
                       {"width": 728, "height": 90}, {"width": 160, "height": 600}):
            with self.subTest(target=target):
                out = get_pipeline("adaptive")(source, target)
                self.assertEqual(validate(source, target, out), [])
                el = next(e for e in out["elements"] if e["id"] == "holiday_watermark")
                self.assertGreater(min(el["width"], el["height"]), 0)
                self.assertAlmostEqual(el["width"] / el["height"], src["width"] / src["height"], places=6)
                box = aabb(el)
                # Either hidden entirely under an opaque shape painted above it
                # (a button), or clear of copy, product and logo.
                covers = [aabb(o) for o in out["elements"]
                          if o["type"] == "shape" and o.get("z_index", 0) > src["z_index"]
                          and o["fill_color"].replace(" ", "").endswith(",1)") and o.get("opacity", 1) == 1]
                if any(c[0] <= box[0] and c[1] <= box[1] and box[2] <= c[2] and box[3] <= c[3] for c in covers):
                    continue
                for other in out["elements"]:
                    if other["type"] == "text" or other["id"] in ("product", "logo"):
                        self.assertLessEqual(overlap_area(box, aabb(other)), 0.5, other["id"])

    def test_metrics_count_missing_placeholder_collisions(self):
        source = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())["source"]
        target = {"width": 1080, "height": 1350}
        out = get_pipeline("anchored")(source, target)
        # The source itself paints the watermark over the legal line.
        self.assertTrue(any("holiday_watermark" in p["a"] + p["b"] for p in metrics(source, out)["overlaps"]))
        placed = place_missing_assets(copy.deepcopy(out), source)
        self.assertFalse(any("holiday_watermark" in p["a"] + p["b"] for p in metrics(source, placed)["overlaps"]))
        self.assertEqual(validate(source, target, placed), [])
        self.assertEqual(place_missing_assets(copy.deepcopy(out), source), placed)


if __name__ == "__main__":
    unittest.main()
