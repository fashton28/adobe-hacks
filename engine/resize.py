"""
Entry point for the resize contract: `resize(source, target_canvas) -> design`.

The implementation lives in `pipelines/` (one folder per approach, see
pipelines/README.md). This function just delegates to the selected pipeline:
set CHAMELEON_PIPELINE=<name> to switch, otherwise pipelines.DEFAULT is used.

See RULES.md and the design schema for the full contract:
- every source element id appears exactly once in the output
- no regenerated imagery; foreground images keep their aspect ratio
- font_size may change; font_family and content must not
- nothing ends up outside the target canvas
"""

from typing import Any

from pipelines import get_pipeline


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    return get_pipeline()(source, target_canvas)
