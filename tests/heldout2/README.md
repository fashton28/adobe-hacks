# Held-out evaluation corpus 2 (blind)

These eight task files were authored blind to the engine on 2026-10-30.
The author did not read `pipelines/` source and did not run the engine or any pipeline on them before committing them here.
They imitate realistic marketing layouts that a hidden scoring set might contain, independent of the engine's assumptions.
Do not tune pipelines against these files: if a change is motivated by one of them, it is no longer held out.
If that happens, write a new held-out task and note the retired one here.

Each file has exactly the shape of the samples in `input/`: `task_id`, `difficulty`, `difficulty_label`, `notes`, `source {canvas, elements}` and `target_canvas`.
Every `source` validates against `chameleon_design_schema_v0.9.json`.
Only the brand kit is used: `solstice_bg_gradient.png`, `solstice_logo_lockup.png`, `solstice_bottle.png`, and the `Solstice Serif` / `Solstice Sans` fonts.
The single exception is `heldout2_08`, which references the intentionally missing asset `solstice_bcorp_badge_2026.png`.
Every `target_canvas` comes from the catalogue in `pipelines/common/formats.py`, and each task's `notes` name the format and size.
Each source was rendered with the official renderer and reviewed visually so that it reads as a credible, finished design.

| File | Source | Target | What it stresses |
|---|---|---|---|
| `heldout2_01_event_poster.json` | 1080x1350 | LinkedIn Banner 1584x396 | Portrait event poster collapsing into a 4:1 strip; grouped date/time/location panel with left-aligned lines; headline color style run; pill CTA group; fine print. |
| `heldout2_02_sale_banner.json` | 1500x500 | Wide Skyscraper Ad 160x600 | Giant "40% OFF" with a colored style run; strikethrough price pair (old price text grouped with a thin line shape); translucent disc behind the product; wide-to-tiny-tall restack. |
| `heldout2_03_app_promo.json` | 1080x1920 | Leaderboard Ad 728x90 | Three stacked CTA button groups with light, solid and ghost fills; showcase group (panel, product, rating); about 20x loss of height. |
| `heldout2_04_quote_card.json` | 1080x1080 | Instagram / TikTok Story 1080x1920 | Long left-aligned italic serif quote; oversized quote glyph with opacity; attribution group; dark text on a solid cream shape; white logo that must stay on the dark band. |
| `heldout2_05_product_grid.json` | 1600x400 | Instagram Post 1080x1080 | Four product groups (card, image, name, price) that should regrid; left text column that must relocate; text link grouped with its underline; uneven name lengths. |
| `heldout2_06_minimal_brand.json` | 1080x1080 | Medium Rectangle Ad 300x250 | Sparse logo-only brand card with large intentional whitespace; thin rule; letter-spaced URL that must stay legible after a 3.6x downscale. |
| `heldout2_07_layered_sticker.json` | 1280x720 | Pinterest Pin 1000x1500 | Solid full-canvas color shape background (no image); translucent scrim via `opacity`; decorative disc bleeding off the top edge; rotated sticker group; right-aligned fine print; z_index layering through a landscape-to-portrait flip. |
| `heldout2_08_infographic_list.json` | 1000x1500 | X / Twitter Header 1500x500 | Five bullet-row groups (ellipse dot, heading, description) that cannot fit as one column at 3:1; solid plum shape background; one intentionally missing image asset that must be kept without crashing. |

Feature coverage across the set:

- `style_runs`: tasks 01 and 02.
- Rotation: task 07 (sticker shape and both labels at -10 degrees).
- `opacity` field: tasks 02, 04 and 07; translucent rgba fills and text colors appear in most tasks.
- `text_align` left, center and right all appear (right in task 07).
- Groups of shape plus text, image plus text, and line plus text.

The official renderer ignores `stroke_color` on rectangles and ellipses, so no task relies on strokes.
`Solstice Serif` has no bold italic face, so no task uses bold italic serif text.

Source renders for review live in `output/heldout2/` (not committed).
