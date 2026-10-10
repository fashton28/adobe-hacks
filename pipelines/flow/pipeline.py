"""Multi-row flow: choose row breaks for arbitrary counts of text, images and groups."""

from itertools import chain

from pipelines.anchored.pipeline import resize as anchored_resize
from pipelines.common.reflow import candidates, select


def resize(source: dict, target_canvas: dict) -> dict:
    return select(source, target_canvas, chain(
        [("anchored", anchored_resize(source, target_canvas))],
        candidates(source, target_canvas, mode="stack"),
        candidates(source, target_canvas, mode="flow"),
    ))
