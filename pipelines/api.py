"""Stable, importable entry point for tools such as the web viewer.

    from pipelines.api import run
    result = run(source, {"width": 728, "height": 90})

`run` never mutates its inputs. It returns a JSON-serializable dict:

    output      the resized design (same contract as engine.resize.resize)
    validation  list of local structural problems (empty when valid)
    metrics     pipelines.common.quality.metrics(source, output)
    score       pipelines.common.quality.score(source, output) - a local proxy
    pipeline    name of the pipeline that produced the output
    elapsed_ms  wall-clock time spent inside the pipeline only

Invalid input (bad canvas, duplicate ids, ...) raises ValueError, as does an
unknown pipeline name. The keys above are a public contract; keep them stable.
"""

import copy
import os
import time

from pipelines import DEFAULT, get_pipeline
from pipelines.common.quality import metrics, score
from pipelines.common.validate import validate


def run(source: dict, target_canvas: dict, pipeline: str | None = None) -> dict:
    name = pipeline or os.environ.get("CHAMELEON_PIPELINE") or DEFAULT
    resize = get_pipeline(name)
    source, target_canvas = copy.deepcopy(source), copy.deepcopy(target_canvas)
    started = time.perf_counter()
    output = resize(source, target_canvas)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "output": output,
        "validation": validate(source, target_canvas, output),
        "metrics": metrics(source, output),
        "score": score(source, output),
        "pipeline": name,
        "elapsed_ms": elapsed_ms,
    }
