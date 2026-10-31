# Held-out evaluation corpus

These six task files were authored independently, before any engine tuning against them.
They exist to catch overfitting to the three public samples in `input/`.
Do not tune pipelines against these files: if a change is motivated by one of them, it is no longer held out.
If that happens, write a new held-out task and note the retired one here.

Each file has the same shape as the samples: `{source: {canvas, elements}, target_canvas}`, plus `task_id`, `difficulty`, `target_format` and `notes` metadata.
Every `source` validates against `chameleon_design_schema_v0.9.json`.
Only the existing brand kit is used: `solstice_bg_gradient.png`, `solstice_logo_lockup.png`, `solstice_bottle.png`, and the `Solstice Serif` / `Solstice Sans` fonts.
Every `target_canvas` comes from the catalogue in `pipelines/common/formats.py` (the `target_format` key names it).

| File | Source | Target | What it stresses |
|---|---|---|---|
| `heldout_01_product_trio.json` | 1280x720 | `story` 1080x1920 | Three repeated product groups (image, name, price) in a row that must restack. |
| `heldout_02_sparse_decor.json` | 1080x1350 | `twitter_header` 1500x500 | Shapes only plus one tiny caption; circles must stay circular, the line thin. |
| `heldout_03_accented_copy.json` | 794x1123 | `youtube_thumb` 1280x720 | Long French, German and Spanish copy with accents, umlauts and eszett. |
| `heldout_04_editorial_columns.json` | 1000x1500 | `facebook_cover` 1640x624 | Two text columns, style runs (italic, bold, color), pull quote, footer group. |
| `heldout_05_layered_groups.json` | 1080x1080 | `pinterest_pin` 1000x1500 | Coincident group, overlapping groups, rotated elements, semi-transparent shapes. |
| `heldout_06_severe_downscale.json` | 1920x1080 | `medium_rect` 300x250 | About 6x linear downscale of ten elements; legibility floor. |

The official renderer ignores `stroke_color` on rectangles and ellipses, so none of these tasks relies on stroke-only shapes.

Run them through a pipeline with the evaluation runner:

```bash
.venv/bin/python -m scripts.run_matrix --input-dir tests/heldout --pipelines adaptive \
  --schema --render --strict-quality --output-dir output/heldout
```
