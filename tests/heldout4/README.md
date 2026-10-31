# Held-out set 4 (blind)

Authored blind on 2026-10-31.
The author did not read the engine, `pipelines/`, any other `tests/heldout*/` set or any `output/` review directory, and did not run the engine on these tasks.

## Files

- `generate.py` writes the eight task JSONs into this directory (run `.venv/bin/python tests/heldout4/generate.py` from the repo root).
- `heldout4_*.json` are the generated tasks, in the same shape as `input/*.json`: `{task_id, difficulty, difficulty_label, notes, source: {canvas, elements}, target_canvas}`.

Every `source` validates against `chameleon_design_schema_v0.9.json` and has unique element ids.
Only `solstice_bg_gradient.png`, `solstice_logo_lockup.png` and `solstice_bottle.png` are used, with the fonts `Solstice Serif` and `Solstice Sans`.
Source renders from the official renderer were reviewed during authoring and live under `output/heldout4/`.

## Renderer-aware authoring

- Shapes never rely on strokes, because the renderer ignores them.
- Translucent text uses an rgba alpha in `color`, never element `opacity`.
- `style_runs` use `end = last index` because the renderer paints `end` inclusively.
- Rotated clusters are rotated rigidly: each piece's centre is moved around the cluster centre and given the same angle.
- Left-aligned logos are offset so the visible mark (not the transparent padding of the lockup) sits on the text margin.

## Tasks

| Task | Source | Target | What it stresses |
|---|---|---|---|
| `heldout4_01_gift_card` | 1500x500 X header | 728x90 leaderboard | Solid dark shape background; a -8 degree rotated gift card cluster (shadow, body, band, kicker, value, note) that must stay rigid; decorative dots; extreme squash to a leaderboard. |
| `heldout4_02_webinar_invite` | 1280x720 YouTube thumbnail | 1080x1920 story | Translucent overlay panel behind the copy column; a speaker card container (avatar ellipse, initials, kicker, name, title, rule, bio); tag pill and CTA pill; landscape to tall. |
| `heldout4_03_loyalty_tiers` | 1080x1350 Instagram portrait | 1600x400 wide banner | Three tier cards in different fills, each holding a dot rating cluster, label, name, points, rule, multi-line perk list and a rate chip; 38 elements; portrait to 4:1. |
| `heldout4_04_recipe_card` | 1000x1500 Pinterest pin | 300x250 medium rectangle | Solid cream shape background with a plum hero band; product over a gold disc; white ingredients panel with an 8-line list; dense four-step method; sage tip panel; footer band; heavy copy into a tiny ad. |
| `heldout4_05_summer_playlist` | 1080x1920 story | 1280x720 YouTube thumbnail | Vinyl record decorative cluster (four stacked ellipses); scattered sparks; 10 degree rotated sticker; two-colour headline via `style_runs`; translucent track list container with three aligned three-column rows. |
| `heldout4_06_store_opening` | 1640x624 Facebook cover | 160x600 skyscraper | Composite map pin (ellipse head, 45 degree rotated square tip, inner disc, product, shadow) that only reads as a pin when kept intact; translucent address panel; sun-ray dot cluster; wide to very narrow. |
| `heldout4_07_pricing_table` | 794x1123 A4 portrait | 1080x1080 Instagram post | Three plan cards with name, big serif price, period, rule, six-line feature list and an inner button; the highlighted middle plan is taller, orange and carries an overlapping MOST POPULAR badge. |
| `heldout4_08_social_proof` | 1080x1080 Instagram post | 1584x396 LinkedIn banner | Three translucent stat cards (accent bar, big number, label); two-colour headline via `style_runs`; italic serif testimonial; translucent decorative halos that bleed past the top and right canvas edges. |

## Feature coverage

- Containers holding content: 02, 03, 04, 05, 06, 07, 08.
- Decorative clusters: 01, 05, 06, 08.
- Coloured text runs: 05, 08.
- Rotation: 01 (card cluster), 05 (sticker), 06 (pin tip).
- Solid shape backgrounds: 01, 04.
- Translucent overlay or panels: 02 (overlay), 05, 06, 08.
- Dense copy: 04.
- Decorative elements deliberately bleeding past the canvas edge in the source: 01 (`glow_big`), 08 (`halo_1`, `halo_2`).
