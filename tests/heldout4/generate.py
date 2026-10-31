"""Generate the blind held-out set 4 task JSONs.

Authored blind on 2026-10-31: written without looking at the engine,
the pipelines or any other held-out set.
Run from the repo root with `.venv/bin/python tests/heldout4/generate.py`.
The script only writes `*.json` files next to itself.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

SERIF = "Solstice Serif"
SANS = "Solstice Sans"

BG = "solstice_bg_gradient.png"
LOGO = "solstice_logo_lockup.png"
BOTTLE = "solstice_bottle.png"

PLUM = "rgba(43,27,46,1)"
INK = "rgba(28,18,34,1)"
ORANGE = "rgba(232,106,58,1)"
GOLD = "rgba(241,178,67,1)"
SAGE = "rgba(125,150,110,1)"
CREAM = "rgba(250,242,228,1)"
WHITE = "rgba(255,255,255,1)"


def white(alpha: float) -> str:
    return f"rgba(255,255,255,{alpha})"


def plum(alpha: float) -> str:
    return f"rgba(43,27,46,{alpha})"


def text(eid, x, y, w, h, content, size, color, *, family=SANS, weight="regular",
         align="left", z=5, **extra):
    el = {
        "id": eid, "type": "text", "x": x, "y": y, "width": w, "height": h, "z_index": z,
        "content": content, "font_family": family, "font_size": size,
        "font_weight": weight, "color": color, "text_align": align,
    }
    el.update(extra)
    return el


def rect(eid, x, y, w, h, fill, *, z=2, radius=0, **extra):
    el = {
        "id": eid, "type": "shape", "x": x, "y": y, "width": w, "height": h, "z_index": z,
        "shape_type": "rectangle", "fill_color": fill,
    }
    if radius:
        el["corner_radius"] = radius
    el.update(extra)
    return el


def ellipse(eid, x, y, w, h, fill, *, z=2, **extra):
    el = {
        "id": eid, "type": "shape", "x": x, "y": y, "width": w, "height": h, "z_index": z,
        "shape_type": "ellipse", "fill_color": fill,
    }
    el.update(extra)
    return el


def image(eid, x, y, w, h, asset, *, z=1, fit="contain", **extra):
    el = {
        "id": eid, "type": "image", "x": x, "y": y, "width": w, "height": h, "z_index": z,
        "asset_id": asset, "fit": fit,
    }
    el.update(extra)
    return el


def left_logo(margin, y, w, *, z=3):
    """Logo whose visible mark (not its transparent padding) starts at `margin`.

    The lockup's artwork spans x 268-632 of its 900 px width.
    """
    return image("logo", round(margin - w * 268 / 900, 1), y, w, round(w / 3), LOGO, z=z)


def pill(prefix, x, y, w, h, fill, label, size, color, *, z=4, group=None, ls=0.0):
    """A button or tag: rounded rectangle plus a vertically centred label."""
    group = group or prefix
    label_h = round(size * 1.3)
    return [
        rect(f"{prefix}_bg", x, y, w, h, fill, z=z, radius=h / 2, group_id=group),
        text(f"{prefix}_label", x, y + round((h - label_h) / 2), w, label_h, label, size,
             color, weight="bold", align="center", z=z + 1, group_id=group,
             letter_spacing=ls),
    ]


def rotate_about(elements, cx, cy, degrees):
    """Rigidly rotate a cluster about (cx, cy).

    The schema rotates each element about its own centre, so each
    element's centre is moved along the circle and given the same angle.
    """
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    for el in elements:
        ex = el["x"] + el["width"] / 2 - cx
        ey = el["y"] + el["height"] / 2 - cy
        nx = cx + ex * cos - ey * sin
        ny = cy + ex * sin + ey * cos
        el["x"] = round(nx - el["width"] / 2, 1)
        el["y"] = round(ny - el["height"] / 2, 1)
        el["rotation"] = degrees
    return elements


def task(task_id, notes, canvas, elements, target):
    return {
        "task_id": task_id,
        "difficulty": "heldout4_blind",
        "difficulty_label": "Held-out 4 - blind professional set",
        "notes": notes,
        "source": {
            "canvas": {"width": canvas[0], "height": canvas[1]},
            "elements": elements,
        },
        "target_canvas": {"width": target[0], "height": target[1]},
    }


# ---------------------------------------------------------------------------
# 01 Gift card - X header -> leaderboard
# ---------------------------------------------------------------------------


def gift_card():
    w, h = 1500, 500
    els = [
        rect("bg", 0, 0, w, h, INK, z=0),
        ellipse("glow_big", 930, -120, 560, 560, plum(1), z=1, group_id="decor"),
        ellipse("dot_gold", 1380, 410, 46, 46, GOLD, z=1, group_id="decor"),
        ellipse("dot_sage", 860, 70, 28, 28, SAGE, z=1, group_id="decor"),
        ellipse("dot_orange", 1420, 60, 18, 18, ORANGE, z=1, group_id="decor"),
        left_logo(64, 34, 210),
        text("eyebrow", 64, 140, 560, 26, "THE GIFTING EDIT", 18, GOLD, weight="bold",
             letter_spacing=4),
        text("headline", 64, 176, 720, 150, "Give the Gift of\nGolden Hour", 62, WHITE,
             family=SERIF, weight="bold", line_height=1.15),
        text("subhead", 64, 334, 700, 34,
             "Digital gift cards from $25, delivered instantly by email.", 22, white(0.82)),
        *pill("cta", 64, 396, 270, 62, ORANGE, "Send a Gift Card", 20, WHITE),
    ]
    # The card cluster: shadow, card body, band and copy, tilted together.
    cx, cy = 1140, 250
    card = [
        rect("card_shadow", 930, 128, 440, 270, "rgba(0,0,0,0.35)", z=2, radius=26,
             group_id="gift_card"),
        rect("card_body", 920, 115, 440, 270, ORANGE, z=3, radius=26, group_id="gift_card"),
        rect("card_band", 920, 290, 440, 46, PLUM, z=4, group_id="gift_card"),
        text("card_kicker", 950, 140, 260, 24, "SOLSTICE GIFT CARD", 16, plum(0.9),
             weight="bold", letter_spacing=2, z=5, group_id="gift_card"),
        text("card_value", 950, 170, 260, 96, "$50", 84, WHITE, family=SERIF, weight="bold",
             z=5, group_id="gift_card"),
        text("card_note", 940, 300, 400, 26, "Redeemable online and in store", 16, CREAM,
             align="center", z=5, group_id="gift_card"),
    ]
    els += rotate_about(card, cx, cy, -8)
    return task(
        "heldout4_01_gift_card",
        "Gift card promo on a solid dark shape background. A tilted card cluster "
        "(shadow, body, band, copy) must stay rigid; extreme squash to a leaderboard.",
        (w, h), els, (728, 90),
    )


# ---------------------------------------------------------------------------
# 02 Webinar invite with speaker card - YouTube thumbnail -> story
# ---------------------------------------------------------------------------


def webinar():
    w, h = 1280, 720
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        rect("overlay", 0, 0, 780, h, "rgba(20,12,28,0.55)", z=1),
        left_logo(64, 40, 210),
        *pill("tag", 64, 146, 200, 40, GOLD, "LIVE WEBINAR", 15, PLUM, ls=2),
        text("headline", 64, 208, 660, 150, "Crafting Botanical Spritzes at Home", 58, WHITE,
             family=SERIF, weight="bold", line_height=1.15),
        text("details", 64, 378, 660, 32, "Thursday, November 12  |  6:00 PM ET  |  45 min",
             22, GOLD, weight="bold"),
        text("body", 64, 428, 620, 90,
             "Join our head mixologist for a live session on balancing citrus, herbs and "
             "sparkle. Bring your questions - we save time for a Q&A.",
             20, white(0.85), line_height=1.45),
        *pill("cta", 64, 566, 260, 64, ORANGE, "Save My Seat", 21, WHITE),
        text("seats", 344, 586, 300, 26, "Free - limited to 500 seats", 17, white(0.7)),
        # Speaker card container.
        rect("speaker_card", 840, 120, 380, 480, CREAM, z=3, radius=28, group_id="speaker"),
        ellipse("speaker_avatar", 950, 160, 160, 160, SAGE, z=4, group_id="speaker"),
        text("speaker_initials", 950, 205, 160, 70, "MR", 54, WHITE, family=SERIF,
             weight="bold", align="center", z=5, group_id="speaker"),
        text("speaker_kicker", 840, 350, 380, 22, "YOUR HOST", 14, ORANGE, weight="bold",
             align="center", letter_spacing=3, z=5, group_id="speaker"),
        text("speaker_name", 840, 378, 380, 46, "Maya Reyes", 36, PLUM, family=SERIF,
             weight="bold", align="center", z=5, group_id="speaker"),
        text("speaker_title", 840, 430, 380, 26, "Head Mixologist, Solstice Bar Lab", 17,
             plum(0.75), align="center", z=5, group_id="speaker"),
        rect("speaker_rule", 900, 482, 260, 2, plum(0.18), z=4, group_id="speaker"),
        text("speaker_bio", 870, 500, 320, 60,
             "12 years behind the bar. Featured in Spirits Weekly and Bar Craft.", 15,
             plum(0.7), align="center", line_height=1.4, z=5, group_id="speaker"),
    ]
    return task(
        "heldout4_02_webinar_invite",
        "Webinar invite: translucent overlay panel behind left copy, a speaker card "
        "container (avatar, initials, name, title, bio) on the right. Landscape to story.",
        (w, h), els, (1080, 1920),
    )


# ---------------------------------------------------------------------------
# 03 Loyalty tiers - Instagram portrait -> wide banner
# ---------------------------------------------------------------------------


def loyalty():
    w, h = 1080, 1350
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        image("logo", 400, 70, 280, 93, LOGO, z=3),
        text("eyebrow", 140, 206, 800, 26, "SOLSTICE REWARDS", 18, GOLD, weight="bold",
             align="center", letter_spacing=5),
        text("headline", 90, 242, 900, 84, "Every Sip Earns You More", 66, WHITE,
             family=SERIF, weight="bold", align="center"),
        text("subhead", 160, 340, 760, 70,
             "Join free and climb three tiers of perks, from birthday treats to private "
             "tastings.", 23, white(0.82), align="center", line_height=1.35),
    ]
    tiers = [
        ("glow", "Glow", "0 - 499 pts", "10% off every order\nBirthday spritz\nMember newsletter",
         CREAM, PLUM, plum(0.7), 1, "1 pt per $1"),
        ("radiance", "Radiance", "500 - 1,499 pts",
         "15% off every order\nFree shipping\nEarly access drops", ORANGE, WHITE, white(0.85), 2,
         "1.5 pts per $1"),
        ("solstice", "Solstice", "1,500+ pts",
         "20% off every order\nPrivate tastings\nLimited-batch gifts", GOLD, PLUM, plum(0.75), 3,
         "2 pts per $1"),
    ]
    for i, (key, name, pts, perks, fill, ink, soft, dots, rate) in enumerate(tiers):
        x = 60 + i * 330
        y = 470
        g = f"tier_{key}"
        els.append(rect(f"{g}_card", x, y, 300, 500, fill, z=2, radius=26, group_id=g))
        for d in range(dots):
            els.append(ellipse(f"{g}_dot{d + 1}", x + 36 + d * 30, y + 40, 20, 20,
                               ink, z=3, group_id=g))
        els += [
            text(f"{g}_label", x + 36, y + 84, 240, 22, f"TIER {i + 1}", 15, soft,
                 weight="bold", letter_spacing=3, z=4, group_id=g),
            text(f"{g}_name", x + 36, y + 112, 240, 50, name, 40, ink, family=SERIF,
                 weight="bold", z=4, group_id=g),
            text(f"{g}_points", x + 36, y + 170, 240, 28, pts, 19, soft, weight="bold", z=4,
                 group_id=g),
            rect(f"{g}_rule", x + 36, y + 222, 228, 2, soft, z=3, group_id=g),
            text(f"{g}_perks", x + 36, y + 246, 240, 150, perks, 20, ink, line_height=1.7,
                 z=4, group_id=g),
            rect(f"{g}_rate_bg", x + 36, y + 414, 228, 50, soft, z=3, radius=25, group_id=g),
            text(f"{g}_rate", x + 36, y + 426, 228, 26, rate, 17, fill, weight="bold",
                 align="center", z=4, group_id=g),
        ]
    els += [
        *pill("cta", 330, 1090, 420, 78, ORANGE, "Join Rewards Free", 24, WHITE),
        text("footnote", 140, 1214, 800, 24,
             "Points never expire while your account is active.", 16, white(0.6),
             align="center"),
    ]
    return task(
        "heldout4_03_loyalty_tiers",
        "Loyalty programme with three tier cards (shape container, dot rating, label, "
        "name, points, rule, perk list). Tall portrait to a 4:1 wide banner.",
        (w, h), els, (1600, 400),
    )


# ---------------------------------------------------------------------------
# 04 Recipe card - Pinterest pin -> medium rectangle (dense copy)
# ---------------------------------------------------------------------------


def recipe():
    w, h = 1000, 1500
    els = [
        rect("bg", 0, 0, w, h, CREAM, z=0),
        rect("hero_band", 0, 0, w, 580, PLUM, z=1),
        ellipse("hero_sun", 560, 90, 390, 390, GOLD, z=2, group_id="hero"),
        image("product", 520, 60, 470, 470, BOTTLE, z=3, group_id="hero"),
        left_logo(60, 40, 200),
        text("eyebrow", 60, 170, 440, 24, "RECIPE NO. 07", 17, GOLD, weight="bold",
             letter_spacing=4),
        text("title", 60, 204, 460, 210, "Blood Orange Rosemary Spritz", 58, WHITE,
             family=SERIF, weight="bold", line_height=1.12),
        text("meta", 60, 440, 460, 30, "Serves 2  |  5 minutes  |  No shaker", 20,
             white(0.78)),
        # Ingredients panel.
        rect("ing_panel", 50, 630, 400, 470, WHITE, z=2, radius=24, group_id="ingredients"),
        text("ing_title", 86, 666, 330, 26, "INGREDIENTS", 18, ORANGE, weight="bold",
             letter_spacing=3, z=4, group_id="ingredients"),
        text("ing_list", 86, 712, 340, 400,
             "1 bottle Solstice Sparkling\n60 ml blood orange juice\n15 ml wild honey syrup\n"
             "2 sprigs fresh rosemary\n1 strip orange zest\nPinch of flaky sea salt\n"
             "Large ice cubes\nSoda water to top",
             21, PLUM, line_height=1.95, z=4, group_id="ingredients"),
        # Method column.
        text("method_title", 500, 666, 440, 26, "METHOD", 18, ORANGE, weight="bold",
             letter_spacing=3, z=4),
        text("method_body", 500, 712, 450, 420,
             "1. Warm the honey syrup with one rosemary sprig for two minutes, then let it "
             "cool so the herb oils settle into the sweetness.\n"
             "2. Fill two tall glasses with large ice. Add the blood orange juice and 7 ml of "
             "the infused syrup to each glass.\n"
             "3. Top slowly with chilled Solstice Sparkling and a splash of soda water. Stir "
             "once from the bottom to keep the bubbles lively.\n"
             "4. Twist the orange zest over the glass, rim with a pinch of salt and finish "
             "with the remaining rosemary.",
             19, plum(0.88), line_height=1.5, z=4),
        rect("tip_panel", 50, 1150, 900, 140, SAGE, z=2, radius=24, group_id="tip"),
        text("tip_title", 86, 1178, 200, 24, "BAR TIP", 17, CREAM, weight="bold",
             letter_spacing=3, z=4, group_id="tip"),
        text("tip_body", 86, 1210, 830, 60,
             "Chill the glasses in the freezer for ten minutes first so the spritz stays "
             "cold and sparkling to the last sip.", 19, WHITE, line_height=1.4, z=4,
             group_id="tip"),
        rect("footer", 0, 1350, w, 150, ORANGE, z=1),
        text("footer_line", 60, 1388, 880, 36, "Pour the light. Find Solstice near you.", 28,
             WHITE, family=SERIF, weight="bold", align="center", z=3),
        text("footer_url", 60, 1436, 880, 26, "solstice.com/recipes", 18, CREAM,
             align="center", z=3, letter_spacing=1),
    ]
    return task(
        "heldout4_04_recipe_card",
        "Recipe card on a solid cream shape background with a plum hero band, a white "
        "ingredient panel and a dense numbered method. Tall pin to a 300x250 ad.",
        (w, h), els, (300, 250),
    )


# ---------------------------------------------------------------------------
# 05 Summer playlist promo - story -> YouTube thumbnail
# ---------------------------------------------------------------------------


def playlist():
    w, h = 1080, 1920
    headline = "Summer Sounds, Bottled."
    start = headline.index("Bottled.")
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        image("logo", 400, 80, 280, 93, LOGO, z=4),
        # Vinyl record cluster.
        ellipse("vinyl_disc", 220, 300, 640, 640, INK, z=2, group_id="vinyl"),
        ellipse("vinyl_groove", 270, 350, 540, 540, white(0.07), z=3, group_id="vinyl"),
        ellipse("vinyl_label", 410, 490, 260, 260, ORANGE, z=4, group_id="vinyl"),
        ellipse("vinyl_hole", 520, 600, 40, 40, GOLD, z=5, group_id="vinyl"),
        ellipse("spark_1", 140, 330, 34, 34, GOLD, z=2, group_id="sparks"),
        ellipse("spark_2", 900, 860, 54, 54, SAGE, z=2, group_id="sparks"),
        ellipse("spark_3", 950, 800, 22, 22, ORANGE, z=2, group_id="sparks"),
        ellipse("spark_4", 110, 900, 20, 20, white(0.6), z=2, group_id="sparks"),
        text("headline", 80, 1010, 920, 250, headline, 104, WHITE, family=SERIF,
             weight="bold", align="center", line_height=1.1,
             style_runs=[{"start": start, "end": len(headline) - 1, "color": GOLD}]),
        # Track list container.
        rect("tracks_panel", 120, 1300, 840, 300, white(0.1), z=2, radius=28, group_id="tracks"),
    ]
    tracks = [("01", "Golden Hour Drive", "3:42"), ("02", "Citrus Skies", "4:05"),
              ("03", "Rooftop at Dusk", "3:18")]
    for i, (num, title, dur) in enumerate(tracks):
        y = 1336 + i * 84
        els += [
            text(f"track{i + 1}_num", 170, y, 70, 40, num, 28, ORANGE, weight="bold", z=4,
                 group_id="tracks"),
            text(f"track{i + 1}_title", 250, y, 520, 40, title, 28, WHITE, z=4,
                 group_id="tracks"),
            text(f"track{i + 1}_time", 780, y, 130, 40, dur, 26, white(0.6), align="right",
                 z=4, group_id="tracks"),
        ]
    els += [
        *pill("cta", 290, 1660, 500, 90, ORANGE, "Stream the Playlist", 30, WHITE),
        text("footnote", 140, 1790, 800, 30, "Curated by Solstice  |  32 tracks  |  2 hr 4 min",
             20, white(0.62), align="center"),
    ]
    sticker = [
        rect("sticker_bg", 700, 290, 300, 84, GOLD, z=6, radius=14, group_id="sticker"),
        text("sticker_label", 700, 314, 300, 36, "NEW EVERY FRIDAY", 22, PLUM, weight="bold",
             align="center", letter_spacing=2, z=7, group_id="sticker"),
    ]
    els += rotate_about(sticker, 850, 332, 10)
    return task(
        "heldout4_05_summer_playlist",
        "Playlist promo: vinyl record decorative cluster, rotated sticker, two-colour "
        "headline (style run), track list container with three aligned rows. Story to 16:9.",
        (w, h), els, (1280, 720),
    )


# ---------------------------------------------------------------------------
# 06 Store opening, map pin - Facebook cover -> skyscraper
# ---------------------------------------------------------------------------


def store_opening():
    w, h = 1640, 624
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        left_logo(72, 36, 240),
        text("eyebrow", 72, 150, 760, 28, "GRAND OPENING  |  SATURDAY, NOV 21", 20, GOLD,
             weight="bold", letter_spacing=3),
        text("headline", 72, 190, 900, 170, "Our First Flagship\nIs Now Open", 70, WHITE,
             family=SERIF, weight="bold", line_height=1.15),
        rect("address_panel", 72, 392, 640, 120, white(0.1), z=2, radius=20, group_id="address"),
        text("address_street", 104, 416, 580, 36, "248 Harbor Street, Portland", 28, WHITE,
             weight="bold", z=4, group_id="address"),
        text("address_hours", 104, 460, 580, 28, "Doors open 10 AM  |  Free tastings all day",
             19, white(0.8), z=4, group_id="address"),
        *pill("cta", 750, 418, 270, 70, ORANGE, "Get Directions", 22, WHITE),
        # Map pin: circle head plus a 45 degree square for the point.
        ellipse("pin_shadow", 1272, 428, 130, 30, "rgba(0,0,0,0.35)", z=2, group_id="pin"),
        rect("pin_tip", 1262, 261, 150, 150, ORANGE, z=3, rotation=45, group_id="pin"),
        ellipse("pin_head", 1187, 80, 300, 300, ORANGE, z=4, group_id="pin"),
        ellipse("pin_inner", 1252, 145, 170, 170, CREAM, z=5, group_id="pin"),
        image("pin_bottle", 1247, 140, 180, 180, BOTTLE, z=6, group_id="pin"),
        # Sun-ray decorative cluster around the pin.
        ellipse("ray_1", 1120, 120, 26, 26, GOLD, z=2, group_id="rays"),
        ellipse("ray_2", 1530, 140, 36, 36, GOLD, z=2, group_id="rays"),
        ellipse("ray_3", 1100, 330, 16, 16, SAGE, z=2, group_id="rays"),
        ellipse("ray_4", 1555, 360, 20, 20, ORANGE, z=2, group_id="rays"),
        ellipse("ray_5", 1490, 60, 14, 14, white(0.7), z=2, group_id="rays"),
    ]
    return task(
        "heldout4_06_store_opening",
        "Store opening with a composite map pin (ellipse head, 45 degree rotated square "
        "tip, inner disc, product, shadow) and an address panel. Wide cover to 160x600.",
        (w, h), els, (160, 600),
    )


# ---------------------------------------------------------------------------
# 07 Pricing table with highlighted plan - A4 portrait -> Instagram post
# ---------------------------------------------------------------------------


def pricing():
    w, h = 794, 1123
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        image("logo", 292, 44, 210, 70, LOGO, z=3),
        text("headline", 47, 142, 700, 62, "Pick Your Pour Plan", 50, WHITE, family=SERIF,
             weight="bold", align="center"),
        text("subhead", 77, 218, 640, 28, "Fresh cases delivered monthly. Skip or cancel any time.",
             19, white(0.8), align="center"),
    ]
    plans = [
        ("starter", "Starter", "$29", ["6 bottles a month", "Two flavours", "Recipe cards",
                                       "Member pricing", "Skip any month", "Email support"],
         False),
        ("classic", "Classic", "$49", ["12 bottles a month", "All flavours", "Free shipping",
                                       "Tasting notes", "Skip any month", "Chat support"],
         True),
        ("reserve", "Reserve", "$89", ["24 bottles a month", "Limited batches", "Free shipping",
                                       "Gift wrapping", "Skip any month", "Priority support"],
         False),
    ]
    for i, (key, name, price, feats, hot) in enumerate(plans):
        x = 40 + i * 245
        g = f"plan_{key}"
        y, ch = (330, 560) if hot else (360, 500)
        fill = ORANGE if hot else CREAM
        ink = WHITE if hot else PLUM
        soft = white(0.82) if hot else plum(0.62)
        els += [
            rect(f"{g}_card", x, y, 224, ch, fill, z=2, radius=22, group_id=g),
            text(f"{g}_name", x + 24, y + 36, 176, 32, name, 22, ink, weight="bold", z=4,
                 group_id=g, letter_spacing=0.5),
            text(f"{g}_price", x + 24, y + 72, 176, 72, price, 58, ink, family=SERIF,
                 weight="bold", z=4, group_id=g),
            text(f"{g}_period", x + 24, y + 146, 176, 22, "per month", 15, soft, z=4,
                 group_id=g),
            rect(f"{g}_rule", x + 24, y + 184, 176, 2, soft, z=3, group_id=g),
            text(f"{g}_features", x + 24, y + 204, 180, 180, "\n".join(feats), 16, ink, line_height=1.8,
                 z=4, group_id=g),
            *pill(f"{g}_btn", x + 24, y + ch - 84, 176, 52, WHITE if hot else PLUM,
                  f"Choose {name}", 16, ORANGE if hot else WHITE, z=4, group=g),
        ]
        if hot:
            els += pill("badge", x + 37, y - 20, 150, 40, PLUM, "MOST POPULAR", 13, GOLD, z=6,
                        ls=2)
    els += [
        text("footnote", 77, 980, 640, 26,
             "Every plan ships free over $40 and includes a 30-day taste guarantee.", 16,
             white(0.7), align="center"),
        text("legal", 77, 1024, 640, 22, "Prices in USD. Taxes calculated at checkout.", 13,
             white(0.5), align="center"),
    ]
    return task(
        "heldout4_07_pricing_table",
        "Pricing table: three plan cards with name, big price, period, feature list and "
        "an inner button; the middle plan is taller, orange and carries an overlapping badge. "
        "A4 flyer to a square post.",
        (w, h), els, (1080, 1080),
    )


# ---------------------------------------------------------------------------
# 08 Social proof stats - Instagram post -> LinkedIn banner
# ---------------------------------------------------------------------------


def stats():
    w, h = 1080, 1080
    headline = "Loved by Sunset Chasers Everywhere"
    start = headline.index("Everywhere")
    els = [
        image("bg", 0, 0, w, h, BG, z=0, fit="cover"),
        ellipse("halo_1", 700, -140, 520, 520, "rgba(232,106,58,0.12)", z=1, group_id="halo"),
        ellipse("halo_2", 860, 120, 260, 260, "rgba(241,178,67,0.12)", z=1, group_id="halo"),
        left_logo(64, 50, 210),
        text("eyebrow", 64, 176, 600, 26, "2026 IN NUMBERS", 18, GOLD, weight="bold",
             letter_spacing=5),
        text("headline", 64, 212, 900, 160, headline, 64, WHITE, family=SERIF, weight="bold",
             line_height=1.15,
             style_runs=[{"start": start, "end": len(headline) - 1, "color": ORANGE}]),
    ]
    items = [
        ("rating", "4.9/5", "Average rating across 18,000 reviews"),
        ("bottles", "120K+", "Bottles poured this summer alone"),
        ("cities", "38", "Cities now pouring Solstice"),
    ]
    for i, (key, num, label) in enumerate(items):
        x = 60 + i * 330
        g = f"stat_{key}"
        els += [
            rect(f"{g}_card", x, 430, 300, 280, white(0.08), z=2, radius=24, group_id=g),
            rect(f"{g}_accent", x + 32, 462, 60, 6, GOLD, z=3, radius=3, group_id=g),
            text(f"{g}_value", x + 32, 492, 250, 104, num, 82, WHITE, family=SERIF,
                 weight="bold", z=4, group_id=g),
            text(f"{g}_label", x + 32, 612, 236, 70, label, 20, white(0.78), line_height=1.4,
                 z=4, group_id=g),
        ]
    els += [
        text("quote", 90, 776, 900, 90,
             "“The only spritz I keep stocked all year, rain or shine.”", 32, WHITE,
             family=SERIF, align="center", font_style="italic", line_height=1.3),
        text("quote_author", 90, 866, 900, 28, "Priya S., Austin", 19, white(0.65),
             align="center", weight="bold", letter_spacing=1),
        text("cta", 90, 948, 900, 34, "Taste why at solstice.com", 24, ORANGE, weight="bold",
             align="center"),
    ]
    return task(
        "heldout4_08_social_proof",
        "Social proof: three translucent stat cards with big serif numbers and labels, "
        "a two-colour headline, italic testimonial and decorative halos. Square to 4:1.",
        (w, h), els, (1584, 396),
    )


BUILDERS = [gift_card, webinar, loyalty, recipe, playlist, store_opening, pricing, stats]


def main() -> None:
    for build in BUILDERS:
        data = build()
        path = HERE / f"{data['task_id']}.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
