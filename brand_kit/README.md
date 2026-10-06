# Solstice brand kit — placeholder assets

These are **stand-in** assets and fonts, generated to unblock rendering and
testing of the 3 sample designs (Level 1/2/3) right now. They are NOT final
production brand assets.

## assets/ (3 files, referenced by `asset_id` in the sample JSONs)

| File | Used as |
|---|---|
| `solstice_bg_gradient.png` | full-bleed background (`fit: cover`) |
| `solstice_logo_lockup.png` | logo (`fit: contain`) — transparent background, white wordmark: invisible against a white viewer, composite onto a dark canvas to check it |
| `solstice_bottle.png` | product image (`fit: contain`) — transparent background |

Do NOT add a `solstice_holiday_badge_2025.png` here — that filename is
intentionally missing in the Level 3 sample, to test that the renderer
handles a missing asset gracefully instead of crashing.

## fonts/ (7 files, matching the `font_family` values in the schema)

- `SolsticeSerif-Regular.ttf`, `SolsticeSerif-Bold.ttf`, `SolsticeSerif-Italic.ttf`
  (renamed from Lora, SIL Open Font License — headline typeface)
- `SolsticeSans-Regular.ttf`, `SolsticeSans-Bold.ttf`, `SolsticeSans-Italic.ttf`,
  `SolsticeSans-BoldItalic.ttf`
  (renamed from Poppins, SIL Open Font License — everything else)

Font family/style/weight metadata is set correctly (verified with `fc-scan`),
so `font_family: "Solstice Serif"` / `"Solstice Sans"` and
`font_weight: "bold"` / `font_style: "italic"` in the schema will resolve to
the right file automatically in any standard font lookup (including
cr-renderer's FontManager once these are folded into `fonts.pickle`).

## Before this goes out to students

Swap this whole folder for the real thing once available:
- actual Solstice brand illustration assets (from the source design files,
  not a flattened poster crop)
- actual Adobe/Solstice brand font files, licensed for redistribution

Both are drop-in replacements — same filenames, same `asset_id`/`font_family`
values, nothing else needs to change.
