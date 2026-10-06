"""A stand-in for `datasets.Features`.

`cr_renderer`'s `_decode_class_label` only ever calls `.items()` on the
features object it's given, and for each key/feature pair it checks whether
`feature` is a `datasets.ClassLabel` or `datasets.Sequence` so it can turn
encoded ints back into strings. Our converter already emits fully-decoded,
plain Python values (real strings, real floats), so there is nothing left to
decode. A plain dict mapping every key `cr_renderer` touches to `None` makes
that decode step a no-op passthrough, without needing a real HuggingFace
`datasets.Features` object or dataset schema at all.
"""

REQUIRED_KEYS = [
    "canvas_width",
    "canvas_height",
    "length",
    "left",
    "top",
    "width",
    "height",
    "angle",
    "type",
    "color",
    "opacity",
    "text",
    "font_size",
    "font",
    "line_height",
    "text_align",
    "capitalize",
    "letter_spacing",
    "font_bold",
    "font_italic",
    "text_color",
    "text_line",
    "image",
]


def make_stub_features() -> dict:
    """Build the stub `Features`-like passthrough dict."""
    return {key: None for key in REQUIRED_KEYS}
