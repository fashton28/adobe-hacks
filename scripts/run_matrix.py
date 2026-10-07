"""Run every input/*.json source against several common target sizes and pipelines.

Prints validation problems and the layout_v1 proxy score per case; with --render,
writes PNGs to output/matrix/. Usage: python -m scripts.run_matrix [--render]
"""

import json
import sys
from pathlib import Path

from pipelines import PIPELINES, get_pipeline
from pipelines.common.validate import validate
from pipelines.layout_v1.pipeline import _score

TARGETS = {
    "instagram_post": (1080, 1080), "instagram_portrait": (1080, 1350), "story": (1080, 1920),
    "youtube_thumb": (1280, 720), "facebook_cover": (1640, 624), "twitter_header": (1500, 500),
    "banner_wide": (1600, 400), "leaderboard": (728, 90), "skyscraper": (160, 600),
    "medium_rect": (300, 250), "a4_portrait": (794, 1123),
}


def main() -> int:
    render = "--render" in sys.argv
    outdir = Path("output/matrix")
    if render:
        outdir.mkdir(parents=True, exist_ok=True)
        from renderer.converter.convert import render_design_to_png
    bad = 0
    print(f"{'source':8} {'target':18} {'pipeline':10} {'score':>7}  problems")
    for f in sorted(Path("input").glob("*.json")):
        src = json.loads(f.read_text())["source"]
        tag = f.stem.split("_")[2]
        for tname, (w, h) in TARGETS.items():
            target = {"width": w, "height": h}
            for p in PIPELINES:
                out = get_pipeline(p)(src, target)
                probs = validate(src, target, out)
                bad += bool(probs) and p != "stretch"
                print(f"{tag:8} {tname:18} {p:10} {_score(src, out):7.2f}  {'; '.join(probs[:2])}")
                if render:
                    render_design_to_png(out, "brand_kit/assets", outdir / f"{tag}_{tname}_{p}.png")
    print(f"\nnon-stretch pipelines with problems: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
