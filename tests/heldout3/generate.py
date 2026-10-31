"""Generate the heldout3 blind task set.

Authored blind on 2026-10-31: written without reading the engine/pipelines
source or the other held-out sets. Every task uses only the three Solstice
brand_kit assets and the Solstice Serif / Solstice Sans fonts.

Usage (from the repo root):
    .venv/bin/python tests/heldout3/generate.py

The script only writes task JSON files into tests/heldout3/.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

BG = "solstice_bg_gradient.png"
LOGO = "solstice_logo_lockup.png"
BOTTLE = "solstice_bottle.png"

SERIF = "Solstice Serif"
SANS = "Solstice Sans"

PLUM = "rgba(43,27,46,1)"
DEEP = "rgba(33,21,38,1)"
ORANGE = "rgba(232,106,58,1)"
GOLD = "rgba(240,178,66,1)"
CREAM = "rgba(250,240,228,1)"
WHITE = "rgba(255,255,255,1)"
SAGE = "rgba(122,150,108,1)"


def rgba(base, alpha):
    """Return `base` (an rgba() string) with a new alpha channel."""
    r, g, b, _ = base[5:-1].split(",")
    return f"rgba({r},{g},{b},{alpha})"


def img(id_, x, y, w, h, asset, fit="contain", **kw):
    return dict(id=id_, type="image", x=x, y=y, width=w, height=h, asset_id=asset, fit=fit, **kw)


def rect(id_, x, y, w, h, fill, radius=0, **kw):
    el = dict(id=id_, type="shape", x=x, y=y, width=w, height=h, shape_type="rectangle", fill_color=fill)
    if radius:
        el["corner_radius"] = radius
    el.update(kw)
    return el


def ell(id_, x, y, w, h, fill, **kw):
    return dict(id=id_, type="shape", x=x, y=y, width=w, height=h, shape_type="ellipse", fill_color=fill, **kw)


def txt(id_, x, y, w, h, content, size, color, family=SANS, bold=False, italic=False,
        align="left", **kw):
    el = dict(id=id_, type="text", x=x, y=y, width=w, height=h, content=content,
              font_family=family, font_size=size, color=color, text_align=align)
    if bold:
        el["font_weight"] = "bold"
    if italic:
        el["font_style"] = "italic"
    el.update(kw)
    return el


def run(content, phrase, occurrence=0, **style):
    """A style run covering `phrase` (end-exclusive, per the schema)."""
    start = -1
    for _ in range(occurrence + 1):
        start = content.index(phrase, start + 1)
    return dict(start=start, end=start + len(phrase), **style)


def finish(elements):
    """Assign z_index from list order unless an element pins its own."""
    for i, el in enumerate(elements):
        el.setdefault("z_index", i)
    return elements


# ---------------------------------------------------------------------------
# 01 - restaurant menu special: square, solid shape background, rotated badge
# ---------------------------------------------------------------------------
def menu_special():
    desc = ("Slow-roasted duck breast with a blood orange and wild honey glaze, "
            "charred fennel, herbed rice pilaf and a splash of smoked rosemary jus.")
    els = [
        rect("bg", 0, 0, 1080, 1080, DEEP),
        ell("deco_sun", 600, -200, 680, 680, ORANGE, opacity=0.18),
        ell("deco_moon", -140, 800, 380, 380, GOLD, opacity=0.12),
        img("logo", 72, 60, 240, 80, LOGO),
        txt("eyebrow", 80, 220, 640, 32, "TONIGHT'S CHEF SPECIAL", 22, GOLD, bold=True,
            letter_spacing=4),
        txt("headline", 80, 268, 700, 210, "Blood Orange Glazed Duck", 84, CREAM, family=SERIF,
            bold=True, line_height=1.15),
        rect("divider", 80, 500, 120, 5, GOLD, radius=2),
        txt("description", 80, 536, 620, 170, desc, 28, rgba(CREAM, 0.82), line_height=1.45),
        ell("price_bg", 770, 520, 230, 230, ORANGE, group_id="price", rotation=-10),
        txt("price_value", 770, 578, 230, 90, "$34", 72, CREAM, family=SERIF, bold=True,
            align="center", group_id="price", rotation=-10),
        txt("price_label", 770, 664, 230, 28, "PER PLATE", 18, CREAM, bold=True, align="center",
            letter_spacing=3, group_id="price", rotation=-10),
        rect("pairing_bg", 80, 760, 660, 140, rgba(WHITE, 0.08), radius=18, group_id="pairing"),
        txt("pairing_label", 112, 786, 400, 26, "PERFECT PAIRING", 17, GOLD, bold=True,
            letter_spacing=3, group_id="pairing"),
        txt("pairing_name", 112, 820, 600, 52, "Solstice Blood Orange Spritz", 36, CREAM,
            family=SERIF, italic=True, group_id="pairing"),
        txt("footer", 80, 966, 920, 34, "Served 5-10 pm daily · Reserve at solstice.com/dine", 22,
            rgba(CREAM, 0.65)),
    ]
    return dict(
        task_id="heldout3_01_menu_special",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Restaurant menu special on a solid shape background (no photo backdrop). "
               "Square to a 728x90 leaderboard: a long serif headline, a 3-line description, "
               "a rotated price badge group and a translucent pairing card must all survive an "
               "8:1 strip. Translucent decorative circles overlap the headline area."),
        source=dict(canvas=dict(width=1080, height=1080), elements=finish(els)),
        target_canvas=dict(width=728, height=90),
    )


# ---------------------------------------------------------------------------
# 02 - newsletter signup card: portrait 4:5 to medium rectangle
# ---------------------------------------------------------------------------
def newsletter():
    els = [
        img("bg", 0, 0, 1080, 1350, BG, fit="cover"),
        ell("deco_glow", -180, -180, 600, 600, WHITE, opacity=0.08),
        img("logo", 390, 64, 300, 100, LOGO),
        rect("card_bg", 120, 240, 840, 880, CREAM, radius=36, group_id="card"),
        img("product", 740, 110, 380, 380, BOTTLE, z_index=20),
        txt("eyebrow", 190, 322, 520, 30, "THE GOLDEN HOUR LETTER", 21, ORANGE, bold=True,
            letter_spacing=3, group_id="card"),
        txt("headline", 190, 372, 560, 240, "Sunset stories, straight to your inbox", 62, PLUM,
            family=SERIF, bold=True, line_height=1.18, group_id="card"),
        txt("body", 190, 640, 700, 150,
            "One short letter a month: new small-batch releases, seasonal recipes and first "
            "access to tasting evenings near you.", 26, rgba(PLUM, 0.75), line_height=1.45,
            group_id="card"),
        rect("email_bg", 190, 810, 700, 96, rgba(PLUM, 0.08), radius=48, group_id="email_field"),
        txt("email_placeholder", 236, 840, 520, 38, "your@email.com", 26, rgba(PLUM, 0.45),
            group_id="email_field"),
        rect("cta_bg", 190, 928, 700, 96, ORANGE, radius=48, group_id="cta"),
        txt("cta_label", 190, 956, 700, 42, "Subscribe - it's free", 28, WHITE, bold=True,
            align="center", group_id="cta"),
        txt("fineprint", 190, 1048, 700, 30, "No spam, ever. Unsubscribe in one click.", 20,
            rgba(PLUM, 0.55), align="center", group_id="card"),
        txt("social_proof", 120, 1190, 840, 40, "Join 48,000 golden hour regulars", 26,
            rgba(CREAM, 0.9), align="center"),
    ]
    return dict(
        task_id="heldout3_02_newsletter_card",
        difficulty="level_2_core",
        difficulty_label="Level 2 - Core",
        notes=("Newsletter signup card on the gradient backdrop. A large cream card group holds "
               "headline, body, a fake email field group and a button group; the product bottle "
               "overlaps the card's top-right corner on purpose. Portrait 4:5 to a 300x250 "
               "medium rectangle, so most copy must shrink hard while the form stays legible."),
        source=dict(canvas=dict(width=1080, height=1350), elements=finish(els)),
        target_canvas=dict(width=300, height=250),
    )


# ---------------------------------------------------------------------------
# 03 - product launch countdown: landscape 16:9 to story
# ---------------------------------------------------------------------------
def countdown():
    head = "Midnight Bloom drops in"
    els = [
        img("bg", 0, 0, 1920, 1080, BG, fit="cover"),
        ell("deco_halo", 130, 170, 720, 720, ORANGE, opacity=0.22),
        img("product", 140, 150, 700, 780, BOTTLE),
        img("logo", 1000, 100, 240, 80, LOGO),
        txt("eyebrow", 1000, 240, 820, 34, "LIMITED RELEASE · 2,000 BOTTLES", 24, GOLD, bold=True,
            letter_spacing=3),
        txt("headline", 1000, 288, 820, 220, head, 88, WHITE, family=SERIF, bold=True,
            line_height=1.15, style_runs=[run(head, "Midnight Bloom", color=GOLD)]),
    ]
    units = [("days", "03", "DAYS"), ("hours", "14", "HOURS"), ("mins", "27", "MINUTES"),
             ("secs", "09", "SECONDS")]
    for i, (key, num, label) in enumerate(units):
        x = 1000 + i * 210
        els += [
            rect(f"count_{key}_bg", x, 550, 180, 200, rgba(WHITE, 0.12), radius=24,
                 group_id=f"count_{key}"),
            txt(f"count_{key}_num", x, 570, 180, 116, num, 96, WHITE, family=SERIF, bold=True,
                align="center", group_id=f"count_{key}"),
            txt(f"count_{key}_label", x, 696, 180, 28, label, 19, GOLD, bold=True, align="center",
                letter_spacing=2, group_id=f"count_{key}"),
        ]
    els += [
        rect("cta_bg", 1000, 820, 380, 96, ORANGE, radius=48, group_id="cta"),
        txt("cta_label", 1000, 846, 380, 46, "Notify Me", 32, WHITE, bold=True, align="center",
            group_id="cta"),
        txt("launch_date", 1410, 848, 420, 40, "Launching 21 June, 9 pm CET", 24,
            rgba(CREAM, 0.8)),
        txt("legal", 1000, 990, 820, 28, "Please enjoy responsibly. 18+ only.", 18,
            rgba(WHITE, 0.5)),
    ]
    return dict(
        task_id="heldout3_03_launch_countdown",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Product launch countdown. Two-column 16:9 layout (large bottle left, copy right) "
               "with a row of four translucent countdown card groups, a two-colour headline "
               "(style_runs) and a button next to a loose date line. Target is a 9:16 story, so "
               "the columns must stack and the four-card row must stay ordered and intact."),
        source=dict(canvas=dict(width=1920, height=1080), elements=finish(els)),
        target_canvas=dict(width=1080, height=1920),
    )


# ---------------------------------------------------------------------------
# 04 - testimonial with rating: story to YouTube thumbnail
# ---------------------------------------------------------------------------
def testimonial():
    quote = ("“I brought a case of Solstice to my sister’s rooftop wedding and by the "
             "first toast every guest was asking where to find it. It tastes like the last warm "
             "evening of summer.”")
    role = "Event planner, Lisbon · Verified buyer"
    els = [
        img("bg", 0, 0, 1080, 1920, BG, fit="cover"),
        txt("quote_mark", 70, 210, 360, 400, "\u201c", 480, rgba(GOLD, 0.35), family=SERIF,
            bold=True),
        img("logo", 390, 90, 300, 100, LOGO),
    ]
    for i in range(5):
        els.append(ell(f"star_{i + 1}", 100 + i * 60, 540, 44, 44, GOLD, group_id="rating"))
    els += [
        txt("rating_label", 410, 542, 420, 42, "4.9 out of 5", 28, CREAM, bold=True,
            group_id="rating"),
        txt("quote", 100, 636, 900, 560, quote, 60, WHITE, family=SERIF, italic=True,
            line_height=1.3),
        rect("divider", 100, 1250, 100, 5, ORANGE, radius=2),
        txt("name", 100, 1286, 520, 56, "Maya Okafor", 40, WHITE, bold=True),
        txt("role", 100, 1348, 520, 84, role, 28, rgba(WHITE, 0.7), line_height=1.4,
            style_runs=[run(role, "Verified buyer", color=GOLD, font_weight="bold")]),
        img("product", 600, 1240, 480, 560, BOTTLE),
        rect("cta_bg", 100, 1580, 480, 100, ORANGE, radius=50, group_id="cta"),
        txt("cta_label", 100, 1608, 480, 46, "Find your bottle", 32, WHITE, bold=True,
            align="center", group_id="cta"),
        txt("url", 100, 1740, 500, 34, "solstice.com/stories", 24, rgba(WHITE, 0.6)),
    ]
    return dict(
        task_id="heldout3_04_testimonial",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Customer testimonial on a 9:16 story: a giant translucent quote glyph behind "
               "a 7-line italic serif quote, a rating group of five dots plus a label, an "
               "attribution with a bold coloured style run, the product bottle and a button. "
               "Target is a 1280x720 YouTube thumbnail, so the long quote must reflow wide "
               "without losing any words."),
        source=dict(canvas=dict(width=1080, height=1920), elements=finish(els)),
        target_canvas=dict(width=1280, height=720),
    )


# ---------------------------------------------------------------------------
# 05 - two-product comparison: wide 3:1 to Pinterest pin
# ---------------------------------------------------------------------------
def comparison():
    def card(key, x, fill, name, price, features, ink, price_ink):
        g = f"card_{key}"
        return [
            rect(f"{g}_bg", x, 50, 520, 500, fill, radius=28, group_id=g),
            img(f"{g}_product", x + 10, 70, 240, 320, BOTTLE, group_id=g),
            txt(f"{g}_name", x + 250, 100, 250, 96, name, 36, ink, family=SERIF, bold=True,
                line_height=1.15, group_id=g),
            txt(f"{g}_price", x + 250, 210, 250, 56, price, 40, price_ink, bold=True, group_id=g),
            txt(f"{g}_features", x + 40, 384, 450, 126, features, 22, rgba(ink, 0.8),
                line_height=1.5, group_id=g),
        ]

    els = [
        img("bg", 0, 0, 1800, 600, BG, fit="cover"),
        img("logo", 70, 56, 240, 80, LOGO),
        txt("headline", 70, 190, 440, 160, "Which glow are you?", 64, WHITE, family=SERIF,
            bold=True, line_height=1.15),
        txt("subhead", 70, 366, 420, 80, "Two small-batch sparklers, one golden hour.", 24,
            rgba(CREAM, 0.8), line_height=1.4),
        rect("cta_bg", 70, 480, 300, 70, ORANGE, radius=35, group_id="cta"),
        txt("cta_label", 70, 498, 300, 36, "Compare & Shop", 24, WHITE, bold=True, align="center",
            group_id="cta"),
    ]
    els += card("a", 560, CREAM, "Blood Orange Spritz", "$6.50",
                "Bright, citrusy and bittersweet\nBest with grilled seafood\n5% ABV · 120 kcal",
                PLUM, ORANGE)
    els += card("b", 1220, GOLD, "Honey Rosemary Fizz", "$7.00",
                "Herbal, golden and softly sweet\nBest with aged cheeses\n4.5% ABV · 110 kcal",
                PLUM, PLUM)
    els += [
        ell("vs_bg", 1070, 220, 160, 160, ORANGE, group_id="vs"),
        txt("vs_label", 1070, 274, 160, 52, "VS", 38, WHITE, bold=True, align="center",
            group_id="vs"),
        rect("new_badge_bg", 1244, 72, 112, 42, PLUM, radius=21, group_id="new_badge"),
        txt("new_badge_label", 1244, 81, 112, 26, "NEW", 18, CREAM, bold=True, align="center",
            letter_spacing=2, group_id="new_badge"),
    ]
    return dict(
        task_id="heldout3_05_product_comparison",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Two-product comparison banner (3:1). Two card groups of five elements each "
               "(the same bottle asset appears twice), a VS badge overlapping both card edges, "
               "a NEW badge on card B and multi-line feature lists with explicit newlines. "
               "Target is a 2:3 Pinterest pin, so the side-by-side cards must stack or shrink "
               "while each card's content stays inside its own card."),
        source=dict(canvas=dict(width=1800, height=600), elements=finish(els)),
        target_canvas=dict(width=1000, height=1500),
    )


# ---------------------------------------------------------------------------
# 06 - festival lineup: portrait 4:5 with very long copy to wide banner
# ---------------------------------------------------------------------------
def festival():
    days = [
        ("FRIDAY", "Marisol Vega · The Lantern Club · Okoye Brothers · Saltwater Choir · "
                   "DJ Amaru · Petal & Pine · Northbound Static · Ines Calloway"),
        ("SATURDAY", "Harbor Lights Orchestra · Kite Season · Mbali Ndlovu · The Velvet Hours · "
                     "Juniper Rail · Sol y Sombra · Tidepool · Ezra Lund Trio · Copper Moth"),
        ("SUNDAY", "Aurora Fields · Little Comets · Rafael Montes · Golden Syrup · "
                   "The Quiet Coast · Hanna & The Hollows · Moonlit Arcade · Desert Bloom "
                   "Collective"),
    ]
    lineup = "\n".join(f"{d}  {names}" for d, names in days)
    runs = [run(lineup, d, color=GOLD, font_weight="bold") for d, _ in days]
    els = [
        img("bg", 0, 0, 1080, 1350, BG, fit="cover"),
        ell("deco_sun", 560, -260, 800, 800, GOLD, opacity=0.16),
        ell("deco_ember", -200, 980, 560, 560, ORANGE, opacity=0.22),
        img("logo", 80, 64, 220, 74, LOGO),
        txt("eyebrow", 80, 196, 600, 32, "SOLSTICE PRESENTS", 22, GOLD, bold=True,
            letter_spacing=4),
        txt("headline", 80, 236, 900, 236, "Golden Hour Sound Festival", 96, WHITE, family=SERIF,
            bold=True, line_height=1.15),
        rect("dates_bg", 80, 496, 520, 64, ORANGE, radius=32, group_id="dates"),
        txt("dates_label", 80, 513, 520, 32, "20-22 JUNE · RIVERSIDE PARK", 22, WHITE, bold=True,
            align="center", letter_spacing=2, group_id="dates"),
        txt("lineup", 80, 600, 940, 500, lineup, 28, WHITE, line_height=1.55, style_runs=runs),
        rect("tickets_bg", 80, 1124, 400, 90, CREAM, radius=45, group_id="tickets"),
        txt("tickets_label", 80, 1148, 400, 44, "Get Tickets", 30, PLUM, bold=True,
            align="center", group_id="tickets"),
        txt("price_note", 510, 1150, 520, 40, "Weekend passes from $89 · Kids under 12 free", 22,
            rgba(WHITE, 0.8)),
        txt("legal", 80, 1270, 920, 28,
            "Presented with Solstice Botanical Sparkling Co. All ages. Lineup subject to change.",
            18, rgba(WHITE, 0.55)),
    ]
    return dict(
        task_id="heldout3_06_festival_lineup",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Festival poster with very long copy: a single lineup text element of three "
               "paragraphs (about 450 characters) with bold gold day names via style_runs, a "
               "two-line display headline, a date pill and a ticket button, plus two large "
               "translucent circles overlapping the copy. Portrait 4:5 to a 1600x400 wide web "
               "banner, so the lineup must stay readable in a short, wide band."),
        source=dict(canvas=dict(width=1080, height=1350), elements=finish(els)),
        target_canvas=dict(width=1600, height=400),
    )


# ---------------------------------------------------------------------------
# 07 - discount coupon with a dashed border: 16:9 to skyscraper
# ---------------------------------------------------------------------------
def coupon():
    big = "25% OFF"
    els = [
        rect("bg", 0, 0, 1600, 900, ORANGE),
        ell("deco_glow", 1150, -260, 720, 720, WHITE, opacity=0.08),
        img("logo", 680, 28, 240, 80, LOGO),
        rect("coupon_bg", 160, 140, 1280, 620, CREAM, radius=24, group_id="coupon"),
        ell("notch_left", 120, 410, 80, 80, ORANGE, group_id="coupon"),
        ell("notch_right", 1400, 410, 80, 80, ORANGE, group_id="coupon"),
    ]
    dash = rgba(PLUM, 0.35)
    n = 0
    for x in range(206, 1380, 60):  # top and bottom edges
        for y in (180, 716):
            n += 1
            els.append(rect(f"dash_{n:02d}", x, y, 36, 4, dash, group_id="dashed_border"))
    for y in (222, 282, 538, 598, 658):  # left and right edges, skipping the notches
        for x in (200, 1396):
            n += 1
            els.append(rect(f"dash_{n:02d}", x, y, 4, 36, dash, group_id="dashed_border"))
    for i, y in enumerate(range(212, 690, 44)):  # stub separator
        els.append(rect(f"stub_dash_{i + 1:02d}", 1078, y, 4, 24, dash, group_id="stub_divider"))
    els += [
        txt("eyebrow", 260, 236, 760, 34, "MEMBERS-ONLY COUPON", 24, ORANGE, bold=True,
            letter_spacing=4),
        txt("discount", 252, 290, 800, 200, big, 168, PLUM, family=SERIF, bold=True,
            line_height=1.1, style_runs=[run(big, "OFF", color=ORANGE)]),
        txt("subtitle", 260, 516, 780, 48, "your next online order of $40 or more", 32,
            rgba(PLUM, 0.8)),
        txt("fineprint", 260, 610, 760, 56,
            "Valid until 31 August 2026. One use per customer. Cannot be combined with other "
            "offers.", 18, rgba(PLUM, 0.6), line_height=1.4),
        txt("code_eyebrow", 1110, 290, 260, 32, "USE CODE", 22, rgba(PLUM, 0.6), bold=True,
            align="center", letter_spacing=3, group_id="code"),
        rect("code_bg", 1120, 336, 240, 84, PLUM, radius=12, group_id="code"),
        txt("code_value", 1120, 356, 240, 46, "GOLDEN25", 32, GOLD, bold=True, align="center",
            letter_spacing=2, group_id="code"),
        txt("code_hint", 1110, 436, 260, 30, "at checkout", 20, rgba(PLUM, 0.6), align="center",
            group_id="code"),
        rect("stamp_bg", 1150, 540, 200, 64, "rgba(200,60,40,1)", radius=8, group_id="stamp",
             rotation=-12, opacity=0.9),
        txt("stamp_label", 1150, 557, 200, 30, "ONLINE ONLY", 20, WHITE, bold=True, align="center",
            letter_spacing=2, group_id="stamp", rotation=-12),
        txt("url", 400, 800, 800, 40, "solstice.com/members", 26, WHITE, bold=True,
            align="center"),
    ]
    return dict(
        task_id="heldout3_07_discount_coupon",
        difficulty="level_3_advanced",
        difficulty_label="Level 3 - Advanced",
        notes=("Discount coupon on a solid orange shape background with a dashed border built "
               "from 50+ tiny rectangles (group dashed_border), a dashed stub divider, ticket "
               "notches that overlap the card edge, a huge two-colour discount figure, a code "
               "box group and a rotated ONLINE ONLY stamp. 16:9 to a 160x600 skyscraper: the "
               "dash pattern has to stay attached to the card and the code must stay readable."),
        source=dict(canvas=dict(width=1600, height=900), elements=finish(els)),
        target_canvas=dict(width=160, height=600),
    )


# ---------------------------------------------------------------------------
# 08 - seasonal greeting with large decorative shapes: square to X header
# ---------------------------------------------------------------------------
def seasonal():
    head = "Happy Summer Solstice"
    els = [
        img("bg", 0, 0, 1080, 1080, BG, fit="cover"),
        ell("ring_outer", 190, -150, 700, 700, GOLD, opacity=0.14),
        ell("ring_inner", 280, -60, 520, 520, ORANGE, opacity=0.3),
        ell("sun", 390, 40, 300, 300, GOLD),
        img("product", 380, 110, 320, 380, BOTTLE),
        txt("headline", 90, 512, 900, 230, head, 92, CREAM, family=SERIF, bold=True,
            align="center", line_height=1.15,
            style_runs=[run(head, "Solstice", color=GOLD, font_weight="regular", font_style="italic")]),
        txt("message", 140, 760, 800, 90,
            "Thank you for a year of golden hours. Here’s to the longest day and the "
            "warmest nights ahead.", 28, rgba(CREAM, 0.85), align="center", line_height=1.45),
        ell("hill_left", -260, 880, 860, 420, rgba(SAGE, 1), opacity=0.55),
        ell("hill_right", 420, 860, 960, 460, DEEP),
        txt("signoff", 240, 900, 600, 46, "With love, the Solstice team", 30, GOLD, family=SERIF,
            italic=True, align="center"),
        img("logo", 440, 966, 200, 66, LOGO),
    ]
    return dict(
        task_id="heldout3_08_seasonal_greeting",
        difficulty="level_2_core",
        difficulty_label="Level 2 - Core",
        notes=("Seasonal greeting card built around large decorative shapes: stacked "
               "translucent sun rings behind the bottle, and two overlapping hill ellipses that "
               "bleed off the canvas and sit under the sign-off and logo. Headline uses an "
               "italic coloured style run. Square to a 3:1 X header: the decoration must be "
               "re-composed, not just squashed, and nothing should land on top of the copy."),
        source=dict(canvas=dict(width=1080, height=1080), elements=finish(els)),
        target_canvas=dict(width=1500, height=500),
    )


TASKS = [menu_special, newsletter, countdown, testimonial, comparison, festival, coupon,
         seasonal]


def main():
    for i, build in enumerate(TASKS, start=1):
        task = build()
        ids = [el["id"] for el in task["source"]["elements"]]
        assert len(ids) == len(set(ids)), f"duplicate ids in {task['task_id']}"
        name = task["task_id"].replace("heldout3_", "")
        path = HERE / f"{name}.json"
        path.write_text(json.dumps(task, indent=2) + "\n")
        print(f"wrote {path.relative_to(HERE.parent.parent)} ({len(ids)} elements)")


if __name__ == "__main__":
    main()
