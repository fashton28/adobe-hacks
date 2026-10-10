"""Asset fidelity, transparent missing assets and product visibility regressions."""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image

from pipelines import get_pipeline
from pipelines.common.assets import asset_info
from pipelines.common.quality import metrics
from pipelines.common.validate import validate
from renderer.converter.assets import _fit_image, load_asset_image
from renderer.converter.brand_fonts import load_brand_font_manager
from renderer.converter.convert import convert_chameleon_to_crello

ROOT = Path(__file__).resolve().parents[1]


class AssetTests(unittest.TestCase):
    def test_contain_preserves_rgba_including_antialiased_edges(self):
        source = Image.new("RGBA", (4, 1))
        source.putdata([(255, 255, 255, a) for a in (1, 64, 128, 255)])
        original = source.tobytes()
        fitted = _fit_image(source, 4, 1, "contain")
        self.assertEqual(fitted.tobytes(), original)
        self.assertEqual(source.tobytes(), original)

    def test_missing_asset_is_transparent_unless_diagnostics_requested(self):
        assets = str(ROOT / "brand_kit/assets")
        name = "solstice_holiday_badge_2025.png"
        clean = load_asset_image(assets, name, 120, 50)
        diagnostic = load_asset_image(assets, name, 120, 50, show_missing_assets=True)
        self.assertEqual(clean.size, (120, 50))
        self.assertIsNone(clean.getchannel("A").getbbox())
        self.assertIsNotNone(diagnostic.getchannel("A").getbbox())
        self.assertFalse((ROOT / "brand_kit/assets" / name).exists())

    def test_converter_retains_missing_element_and_warning_without_error_artwork(self):
        source = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())["source"]
        element = next(e for e in source["elements"] if e["type"] == "image" and not asset_info(e["asset_id"])["available"])
        design = dict(source, elements=[element])
        original = copy.deepcopy(design)
        fonts = load_brand_font_manager(str(ROOT / "brand_kit/fonts"))
        example, warnings = convert_chameleon_to_crello(design, fonts, str(ROOT / "brand_kit/assets"))
        self.assertEqual(example["length"], 1)
        self.assertEqual(design, original)
        self.assertTrue(any(element["asset_id"] in w and "not painted" in w for w in warnings))
        self.assertIsNone(example["image"][0].getchannel("A").getbbox())
        debug, warnings = convert_chameleon_to_crello(design, fonts, str(ROOT / "brand_kit/assets"), show_missing_assets=True)
        self.assertIsNotNone(debug["image"][0].getchannel("A").getbbox())
        self.assertTrue(any("diagnostic placeholder" in w for w in warnings))

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
        self.assertGreater(q["min_font"], 16)
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


if __name__ == "__main__":
    unittest.main()
