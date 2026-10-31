"""Round 4 fidelity rules: containment composites, occlusion, contrast, motifs, bridges and gutters."""

import unittest

from pipelines.adaptive.pipeline import search
from pipelines.common.fidelity import check
from pipelines.common.units import build_units
from pipelines.common.validate import validate


def _shape(id_, x, y, w, h, fill="rgba(250,240,228,1)", z=1, **extra):
    return {"id": id_, "type": "shape", "shape_type": extra.pop("shape_type", "rectangle"), "x": x, "y": y,
            "width": w, "height": h, "fill_color": fill, "z_index": z, **extra}


def _text(id_, x, y, w, h, size, content, color="rgba(43,27,46,1)", z=5, **extra):
    return {"id": id_, "type": "text", "x": x, "y": y, "width": w, "height": h, "content": content,
            "font_family": "Solstice Sans", "font_size": size, "color": color, "z_index": z, **extra}


def _design(W, H, *elements, bg="rgba(44,25,46,1)"):
    return {"canvas": {"width": W, "height": H},
            "elements": [_shape("bg", 0, 0, W, H, bg, z=0), *elements]}


def newsletter():
    """A cream card holding copy, a faint form field group and a button group, on a dark backdrop."""
    return _design(1080, 1350,
                   _shape("card", 120, 240, 840, 880, z=2, group_id="card"),
                   _text("title", 190, 300, 700, 200, 72, "Sunset stories, straight to your inbox", z=3,
                         group_id="card"),
                   _shape("field", 190, 810, 700, 96, "rgba(43,27,46,0.08)", z=4, group_id="field"),
                   _text("field_hint", 236, 840, 520, 38, 28, "your@email.com", "rgba(43,27,46,0.45)", z=5,
                         group_id="field"),
                   _shape("button", 190, 928, 700, 96, "rgba(232,106,58,1)", z=6, group_id="cta"),
                   _text("button_label", 190, 956, 700, 42, 30, "Subscribe", "rgba(255,255,255,1)", z=7,
                         group_id="cta", text_align="center"),
                   _text("proof", 120, 1190, 840, 40, 28, "Join 48,000 regulars", "rgba(250,240,228,0.9)", z=8))


class ContainmentTests(unittest.TestCase):
    def test_content_inside_a_card_joins_the_card_unit(self):
        source = newsletter()
        card = next(u for u in build_units(source) if 1 in u["idx"])
        members = {source["elements"][i]["id"] for i in card["idx"]}
        self.assertTrue({"card", "title", "field", "field_hint", "button", "button_label"} <= members)
        self.assertNotIn("proof", members)

    def test_resized_form_stays_inside_its_card_and_visible(self):
        source = newsletter()
        for target in ({"width": 300, "height": 250}, {"width": 1600, "height": 400}, {"width": 1080, "height": 1920}):
            out, info = search(source, target)
            self.assertTrue(info["valid"], target)
            self.assertEqual(check(source, out)["violations"], 0, (target, check(source, out)["details"]))

    def test_moving_the_field_off_the_card_is_a_violation(self):
        source = newsletter()
        out = {"canvas": dict(source["canvas"]), "elements": [dict(e) for e in source["elements"]]}
        for el in out["elements"]:
            if el["id"] in ("field", "field_hint"):
                el["y"] += 380  # below the card, onto the dark backdrop
        kinds = {d[0] for d in check(source, out)["details"]}
        self.assertTrue({"escaped", "contrast", "indistinct"} <= kinds, kinds)


class OcclusionAndContrastTests(unittest.TestCase):
    def test_opaque_shape_painted_over_copy_is_a_violation(self):
        source = _design(1000, 1000, _text("msg", 100, 100, 600, 80, 40, "Thank you for a year", "rgba(255,255,255,1)",
                                           z=2),
                         _shape("hill", 600, 800, 400, 200, "rgba(33,21,38,1)", z=3, shape_type="ellipse"))
        out = {"canvas": dict(source["canvas"]), "elements": [dict(e) for e in source["elements"]]}
        out["elements"][2].update(x=300, y=50)  # the hill now sits on the message
        self.assertIn("occluded", {d[0] for d in check(source, out)["details"]})

    def test_style_run_colour_matching_the_backdrop_is_a_violation(self):
        run = [{"start": 4, "end": 7, "color": "rgba(232,106,58,1)"}]
        source = _design(1000, 600, _shape("card", 100, 100, 800, 400, z=1),
                         _text("offer", 150, 200, 700, 150, 120, "25% OFF", z=2, style_runs=run),
                         bg="rgba(232,106,58,1)")
        out = {"canvas": dict(source["canvas"]), "elements": [dict(e) for e in source["elements"]]}
        out["elements"][2].update(y=440, height=150)  # mostly off the card, onto the orange field
        out["elements"][2]["y"] = 450
        self.assertIn("contrast", {d[0] for d in check(source, out)["details"]})


class MotifTests(unittest.TestCase):
    def sun(self):
        return _design(1080, 1080,
                       _shape("ring", 190, -150, 700, 700, "rgba(240,178,66,1)", z=1, shape_type="ellipse", opacity=0.2),
                       _shape("core", 390, 40, 300, 300, "rgba(240,178,66,1)", z=2, shape_type="ellipse"),
                       _shape("disc", 420, 200, 240, 240, "rgba(232,106,58,1)", z=3, shape_type="ellipse"),
                       _text("headline", 90, 600, 900, 200, 96, "Happy Summer Solstice", "rgba(250,240,228,1)", z=4))

    def test_overlapping_art_is_one_motif_and_rings_follow_it(self):
        source = self.sun()
        units = build_units(source)
        motif = next(u for u in units if 2 in u["idx"])
        self.assertIn(3, motif["idx"])
        ring = next(u for u in units if u["idx"] == [1])
        self.assertEqual(ring["kind"], "decor")
        self.assertIs(units[ring["follow"]], motif)

    def test_rings_stay_concentric_and_on_canvas(self):
        source = self.sun()
        out, _ = search(source, {"width": 1500, "height": 500})
        by_id = {e["id"]: e for e in out["elements"]}
        ring, core = by_id["ring"], by_id["core"]
        rc = (ring["x"] + ring["width"] / 2, ring["y"] + ring["height"] / 2)
        cc = (core["x"] + core["width"] / 2, core["y"] + core["height"] / 2)
        self.assertLess(abs(rc[0] - cc[0]) + abs(rc[1] - cc[1]), 0.25 * core["width"] + 2)
        self.assertGreaterEqual(ring["y"], -0.5)

    def test_huge_bleeding_ring_never_forces_its_follower_off_canvas(self):
        source = _design(1080, 1080,
                         _shape("ring", -1960, 290, 5000, 500, "rgba(255,200,100,0.3)", z=1, shape_type="ellipse"),
                         {"id": "bottle", "type": "image", "asset_id": "solstice_bottle.png",
                          "x": 340, "y": 340, "width": 400, "height": 400, "z_index": 3},
                         _text("h", 100, 900, 880, 100, 60, "Summer drop", "rgba(255,255,255,1)", z=4))
        for target in ({"width": 1080, "height": 1080}, {"width": 300, "height": 250},
                       {"width": 160, "height": 600}, {"width": 50, "height": 50}):
            with self.subTest(target=target):
                out, _ = search(source, target)
                self.assertEqual(validate(source, target, out), [])


class BridgeAndGutterTests(unittest.TestCase):
    def cards(self):
        def card(name, x, z):
            return [_shape(f"{name}_bg", x, 50, 520, 500, z=z, group_id=name),
                    _text(f"{name}_title", x + 30, 100, 400, 60, 40, "Blood Orange", z=z + 1, group_id=name)]
        return _design(1800, 600, *card("a", 560, 2), *card("b", 1220, 4),
                       _shape("vs_bg", 1070, 220, 160, 160, "rgba(232,106,58,1)", z=8, group_id="vs",
                              shape_type="ellipse"),
                       _text("vs_label", 1070, 274, 160, 52, 38, "VS", "rgba(255,255,255,1)", z=9, group_id="vs",
                             text_align="center"))

    def test_badge_between_two_cards_is_a_bridge_placed_between_them(self):
        source = self.cards()
        units = build_units(source)
        bridge = next(u for u in units if u["kind"] == "bridge")
        self.assertEqual({source["elements"][i]["id"] for i in bridge["idx"]}, {"vs_bg", "vs_label"})
        out, _ = search(source, {"width": 1000, "height": 1500})
        by_id = {e["id"]: e for e in out["elements"]}
        a, b, vs = by_id["a_bg"], by_id["b_bg"], by_id["vs_bg"]
        (ax, ay), (bx, by), (vx, vy) = (((e["x"] + e["width"] / 2), (e["y"] + e["height"] / 2)) for e in (a, b, vs))
        self.assertLess(abs(vx - (ax + bx) / 2) + abs(vy - (ay + by) / 2), 0.1 * a["width"])

    def test_cards_in_a_row_never_abut(self):
        source = self.cards()
        out, _ = search(source, {"width": 1600, "height": 400})
        by_id = {e["id"]: e for e in out["elements"]}
        a, b = sorted((by_id["a_bg"], by_id["b_bg"]), key=lambda e: (e["x"], e["y"]))
        if abs(a["y"] - b["y"]) < 1:  # side by side
            self.assertGreaterEqual(b["x"] - (a["x"] + a["width"]), 4.0)
