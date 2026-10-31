# heldout3 - blind held-out task set

Authored blind on 2026-10-31.
The author did not read the engine or `pipelines/` source (other than the target catalogue in `pipelines/common/formats.py`), the other held-out sets, or any review output, and did not run the engine while designing these tasks.
Use this set to check generalisation, not to tune against.

## Contents

- `generate.py` writes every task JSON in this folder and only writes here.
  Run it from the repo root with `.venv/bin/python tests/heldout3/generate.py`.
- Eight task files in the same shape as `input/*.json`: `task_id`, `difficulty`, `difficulty_label`, `notes`, `source` (`canvas` plus `elements`) and `target_canvas`.
- Every `source` validates against `chameleon_design_schema_v0.9.json`.
- Assets are limited to `solstice_bg_gradient.png`, `solstice_logo_lockup.png` and `solstice_bottle.png`, and fonts to Solstice Serif and Solstice Sans.
- No asset is missing on purpose in this set.

## Tasks

| File | Source | Target | Elements | What it stresses |
|---|---|---|---|---|
| `01_menu_special.json` | 1080x1080 square | 728x90 leaderboard | 15 | Solid shape background (no photo), long two-line serif headline, 4-line description, rotated price badge group, translucent pairing card, translucent circles behind the copy |
| `02_newsletter_card.json` | 1080x1350 portrait 4:5 | 300x250 medium rectangle | 14 | Big cream card group with a fake email field group and a button group nested on top of it, bottle deliberately overlapping the card corner, heavy downscale where the form must stay legible |
| `03_launch_countdown.json` | 1920x1080 landscape 16:9 | 1080x1920 story | 22 | Two-column layout that must stack, a row of four translucent countdown card groups that must keep their order, two-colour headline via `style_runs`, button beside a loose date line |
| `04_testimonial.json` | 1080x1920 story 9:16 | 1280x720 YouTube thumbnail | 17 | Very large translucent quote glyph, 6-line italic serif quote, rating group of five dots plus label, attribution with a bold coloured style run, bottle and button |
| `05_product_comparison.json` | 1800x600 wide 3:1 | 1000x1500 Pinterest pin | 20 | Two five-element card groups using the same bottle asset twice, VS badge overlapping both card edges, NEW badge on a card, feature lists with explicit newlines |
| `06_festival_lineup.json` | 1080x1350 portrait 4:5 | 1600x400 wide web banner | 13 | Very long copy: one lineup text element of three paragraphs (about 450 characters) with bold gold day names via `style_runs`, display headline, date pill, ticket button, large translucent circles overlapping copy |
| `07_discount_coupon.json` | 1600x900 landscape 16:9 | 160x600 skyscraper | 78 | Solid shape background, dashed border built from 50+ tiny rectangles, dashed stub divider, ticket notches overlapping the card edge, huge two-colour discount figure, code box group, rotated stamp group |
| `08_seasonal_greeting.json` | 1080x1080 square | 1500x500 X header | 11 | Large decorative shapes: stacked translucent sun rings behind the bottle and overlapping hill ellipses that bleed off the canvas under the sign-off and logo, italic coloured style run in the headline, no groups at all |

## Feature coverage

- Groups (buttons, badges, cards, form field, countdown cards, coupon border): tasks 01 to 07.
- Overlapping decoration: tasks 01, 02, 05, 06, 07 and 08.
- Translucent shapes (element `opacity` or an alpha `fill_color`): tasks 01, 02, 03, 06, 07 and 08.
- Translucent text (alpha in `color`): every task, and a large decorative glyph in task 04.
- `style_runs`: tasks 03, 04, 06, 07 and 08.
- Rotation: tasks 01 (price badge) and 07 (ONLINE ONLY stamp).
- Text-only background (solid shape instead of the gradient image): tasks 01 and 07.
- Very long copy: task 06 (and a long quote in task 04).
- Targets cover leaderboard, medium rectangle, story, YouTube thumbnail, Pinterest pin, wide web banner, skyscraper and X header.

## Authoring notes

- The official renderer ignores shape strokes, so no task relies on `stroke_color`; the coupon's dashed border is made of filled rectangles.
- The renderer does not appear to apply element `opacity` to text, so translucent text uses an alpha channel in `color` instead.
- Solstice Serif has no bold italic face, so the italic run in task 08 also sets `font_weight` to regular.
- `style_runs` use the schema's end-exclusive indices.
- Source renders made with the official renderer on macOS (not in the container) were reviewed for design quality during authoring and kept under `output/heldout3/`.
