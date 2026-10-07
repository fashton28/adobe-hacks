"""Pipeline registry.

Each pipeline is a folder under `pipelines/` exposing
`resize(source, target_canvas) -> design` (same contract as
`engine.resize.resize`). `engine/resize.py` delegates to `get_pipeline()`.

Select one with the CHAMELEON_PIPELINE env var; otherwise DEFAULT is used.
"""

import importlib
import os
from typing import Callable

PIPELINES = {
    "stretch": "pipelines.baseline_stretch.pipeline",
    "anchored": "pipelines.anchored.pipeline",
    "layout_v1": "pipelines.layout_v1.pipeline",
}
DEFAULT = "layout_v1"


def get_pipeline(name: str | None = None) -> Callable:
    name = name or os.environ.get("CHAMELEON_PIPELINE") or DEFAULT
    if name not in PIPELINES:
        raise ValueError(f"Unknown pipeline '{name}'. Available: {sorted(PIPELINES)}")
    return importlib.import_module(PIPELINES[name]).resize
