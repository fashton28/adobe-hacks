"""Compare resize pipelines using contract checks, quality metrics and real previews.

python -m scripts.run_matrix --render --variants --include-source
Reports are development proxies, not official challenge scores.
"""

import argparse
import copy
import hashlib
import html
import importlib.metadata
import importlib.util
import json
import platform
import statistics
import time
from pathlib import Path

from pipelines import PIPELINES, get_pipeline
from pipelines.common.formats import TARGETS
from pipelines.common.quality import BACKDROP_SLACK, EMPTY_GROWTH, metrics, score
from pipelines.common.validate import validate

ROOT = Path(__file__).resolve().parents[1]


def summarize(records):
    """Report failures and worst cases before aggregate heuristic scores."""
    summary = {}
    for name in dict.fromkeys(r["pipeline"] for r in records):
        rows = [r for r in records if r["pipeline"] == name]
        measured = [r for r in rows if "metrics" in r]
        text_rows = [r for r in measured if r["metrics"]["texts"]]
        durations = sorted(r["elapsed_ms"] for r in rows)
        summary[name] = {
            "cases": len(rows), "contract_failures": sum(bool(r["problems"]) for r in rows),
            "quality_failures": sum(bool(r.get("quality_problems")) for r in rows),
            "overflow_cases": sum(r["metrics"]["text_overflows"] > 0 for r in measured),
            "overlap_cases": sum(r["metrics"]["overlap_pairs"] > 0 for r in measured),
            "fidelity_cases": sum(r["metrics"].get("fidelity_violations", 0) > 0 for r in measured),
            "backdrop_cases": sum(r["metrics"]["backdrop_shortfall"] > BACKDROP_SLACK for r in measured),
            "empty_canvas_cases": sum(r["metrics"]["empty_output"] - r["metrics"]["empty_source"] > EMPTY_GROWTH
                                      for r in measured),
            "below_6px": sum(r["metrics"]["below_6px"] for r in measured),
            "below_10px": sum(r["metrics"]["below_10px"] for r in measured),
            "worst_min_font": min((r["metrics"]["min_font"] for r in text_rows), default=None),
            "median_min_font": statistics.median(r["metrics"]["min_font"] for r in text_rows) if text_rows else None,
            "median_ms": statistics.median(durations),
            "p95_ms": durations[max(0, (95 * len(durations) + 99) // 100 - 1)],
        }
    return summary


def variants(source):
    """Deterministic stress cases; ids and annotations must not encode roles."""
    renamed = copy.deepcopy(source)
    groups = {}
    for i, el in enumerate(renamed["elements"]):
        el["id"] = f"element-{i}"
        if el.get("group_id"):
            groups.setdefault(el["group_id"], f"group-{len(groups)}")
            el["group_id"] = groups[el["group_id"]]
        for key in list(el):
            if key.startswith("_"):
                del el[key]
    yield "renamed", renamed
    longer = copy.deepcopy(source)
    for el in longer["elements"]:
        if el["type"] == "text" and not el.get("group_id"):
            el["content"] += " Discover the collection and explore every botanical flavor."
    yield "long_copy", longer
    rotated = copy.deepcopy(source)
    for el in rotated["elements"]:
        if el.get("group_id"):
            el["rotation"] = 35
    yield "rotated_groups", rotated


def write_html(outdir, records, sources):
    def esc(value):
        return html.escape(str(value), quote=True)

    parts = ["<!doctype html><html><meta charset='utf-8'><title>Pipeline comparison</title>",
             ("<style>body{font:15px system-ui;margin:24px;background:#f5f5f5}"
              "section{margin:24px 0}.cases{display:flex;flex-wrap:wrap;gap:16px}"
              "article{background:white;padding:12px;width:340px}"
              "img{max-width:100%;max-height:300px;object-fit:contain}"
              "pre{white-space:pre-wrap}.bad{color:#a00}</style>"),
             ("<h1>Pipeline comparison</h1><p>Local proxies; not official scores. "
              "Click a PNG to inspect native resolution. Missing assets render as the "
              "official placeholder box and are listed as warnings.</p>")]
    keys = list(dict.fromkeys((r["source"], r["target"]) for r in records))
    for source, target in keys:
        parts.append(f"<section><h2>{esc(source)} / {esc(target)}</h2><div class='cases'>")
        if source in sources:
            path = esc(sources[source])
            parts.append(f"<article><b>Source</b><p><a href='{path}'><img src='{path}'></a></article>")
        for r in (r for r in records if (r["source"], r["target"]) == (source, target)):
            parts.append(f"<article><b>{esc(r['pipeline'])}</b>")
            if r.get("png"):
                path = esc(r["png"])
                parts.append(f"<p><a href='{path}'><img src='{path}'></a>")
            q = r.get("metrics", {})
            parts.append(f"<p>Score {r.get('score', 0):.2f}; {r['elapsed_ms']:.0f} ms<br>"
                         f"Minimum font {q.get('min_font', 0):.1f}px; below 6px: {q.get('below_6px', 0)}<br>"
                         f"Text overflows: {q.get('text_overflows', 0)}; overlaps: {q.get('overlap_pairs', 0)}; "
                         f"fidelity violations: {q.get('fidelity_violations', 0)}</p>")
            parts.append(f"<p>Source arrangement shift: {q.get('layout_shift', 0):.3f}<br>"
                         f"Backdrop coverage: {q.get('backdrop_coverage') if q.get('backdrop_coverage') is None else format(q['backdrop_coverage'], '.0%')}; "
                         f"empty canvas: {q.get('empty_output', 0):.0%} (source {q.get('empty_source', 0):.0%})</p>")
            if r["problems"] or r.get("quality_problems"):
                parts.append(f"<pre class='bad'>{esc('; '.join(r['problems'] + r.get('quality_problems', [])))}</pre>")
            if r.get("search"):
                parts.append(f"<p>Selected: {esc(r['search']['selected'])}; "
                             f"candidates: {r['search']['evaluated']}</p>")
            if r.get("render_warnings"):
                parts.append(f"<pre>{esc('; '.join(r['render_warnings']))}</pre>")
            if r.get("json"):
                parts.append(f"<a href='{esc(r['json'])}'>Output JSON</a>")
            parts.append("</article>")
        parts.append("</div></section>")
    (outdir / "index.html").write_text("\n".join(parts) + "</html>", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true", help="Use the real renderer; no box fallback")
    parser.add_argument("--pipelines", nargs="+", choices=sorted(PIPELINES), default=list(PIPELINES))
    parser.add_argument("--targets", nargs="+", choices=sorted(TARGETS), default=list(TARGETS))
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/matrix"))
    parser.add_argument("--variants", action="store_true")
    parser.add_argument("--include-source", action="store_true", help="Also test the original canvas")
    parser.add_argument("--task-only", action="store_true",
                        help="Only each task's requested target (plus the source canvas with --include-source)")
    parser.add_argument("--check-determinism", action="store_true")
    parser.add_argument("--strict-quality", action="store_true",
                        help="Fail for text overflow, unrelated unit overlap, a lost backdrop or a mostly empty canvas")
    parser.add_argument("--schema", action="store_true", help="Validate the supplied JSON schema (requirements-dev.txt)")
    parser.add_argument("--min-font", type=float, default=0, help="Optional readability gate in pixels; not an official threshold")
    parser.add_argument("--reference-pipelines", nargs="*", choices=sorted(PIPELINES), default=["stretch"],
                        help="Report these pipelines without gating the exit status")
    args = parser.parse_args(argv)
    files = sorted(args.input_dir.glob("*.json"))
    if not files:
        parser.error(f"No input JSON files in {args.input_dir}")
    if not 0 <= args.min_font < float("inf"):
        parser.error("--min-font must be finite and nonnegative")
    code_hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for folder in ("pipelines", "renderer", "scripts") for p in sorted((ROOT / folder).rglob("*.py"))}
    schema_validator = None
    if args.schema:
        from jsonschema import Draft202012Validator
        schema_validator = Draft202012Validator(json.loads((ROOT / "chameleon_design_schema_v0.9.json").read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    render = None
    if args.render:
        from renderer.converter.convert import render_design_to_png
        render = render_design_to_png
    records, source_pngs, bad = [], {}, 0
    print(f"{'source':42} {'target':18} {'pipeline':10} {'score':>7} {'min px':>7} {'<6':>3} {'clip':>4} {'ovlp':>4} {'fid':>4} {'ms':>7}  problems", flush=True)
    for path in files:
        task = json.loads(path.read_text(encoding="utf-8"))
        src = task["source"]
        cases = [(path.stem, src)]
        if args.variants:
            cases.extend((f"{path.stem}_{name}", design) for name, design in variants(src))
        for tag, source in cases:
            if render:
                source_png = f"{tag}_source.png"
                render(source, ROOT / "brand_kit/assets", args.output_dir / source_png,
                       max_size=max(source["canvas"].values()))
                source_pngs[tag] = source_png
            source_json = f"{tag}_source.json"
            (args.output_dir / source_json).write_text(json.dumps(source, indent=2, allow_nan=False), encoding="utf-8")
            targets = {} if args.task_only else {name: TARGETS[name] for name in args.targets}
            # Always include the task's actual requested target, even if the
            # development catalogue changes or a fixture uses another size.
            task_target = task.get("target_canvas")
            if task_target and (task_target["width"], task_target["height"]) not in targets.values():
                targets["task_target"] = (task_target["width"], task_target["height"])
            if args.include_source:
                targets["source_canvas"] = (source["canvas"]["width"], source["canvas"]["height"])
            for tname, (w, h) in targets.items():
                target = {"width": w, "height": h}
                for name in args.pipelines:
                    original, target_before = copy.deepcopy(source), target.copy()
                    started = time.perf_counter()
                    r = {"source": tag, "source_json": source_json, "target": tname,
                         "canvas": target.copy(), "pipeline": name, "problems": [], "quality_problems": []}
                    try:
                        if name == "adaptive":
                            from pipelines.adaptive.pipeline import search
                            out, r["search"] = search(source, target)
                        else:
                            out = get_pipeline(name)(source, target)
                        r["elapsed_ms"] = (time.perf_counter() - started) * 1000
                        r["problems"] = validate(original, target_before, out)
                        if schema_validator:
                            r["problems"].extend(f"schema {list(e.path)}: {e.message}" for e in schema_validator.iter_errors(out))
                        if source != original or target != target_before:
                            r["problems"].append("input mutated")
                        if args.check_determinism:
                            repeat_source, repeat_target = copy.deepcopy(original), target_before.copy()
                            if out != get_pipeline(name)(repeat_source, repeat_target):
                                r["problems"].append("nondeterministic output")
                            if repeat_source != original or repeat_target != target_before:
                                r["problems"].append("repeat input mutated")
                        measured, value = metrics(original, out), score(original, out)
                        # A broken pipeline must not poison the entire report
                        # with NaN/Infinity after its contract failure is logged.
                        json.dumps({"metrics": measured, "score": value}, allow_nan=False)
                        r["metrics"], r["score"] = measured, value
                        q = r["metrics"]
                        if args.strict_quality:
                            if q["text_overflows"]:
                                r["quality_problems"].append("text overflow")
                            if q["overlap_pairs"]:
                                r["quality_problems"].append("unrelated unit overlap")
                            if q["backdrop_shortfall"] > BACKDROP_SLACK:
                                r["quality_problems"].append(
                                    f"backdrop covers {q['backdrop_coverage']:.0%} of the canvas")
                            if q["empty_output"] - q["empty_source"] > EMPTY_GROWTH:
                                r["quality_problems"].append(
                                    f"empty canvas {q['empty_output']:.0%} vs {q['empty_source']:.0%} in source")
                        if q["texts"] and q["min_font"] < args.min_font:
                            r["quality_problems"].append(f"font below {args.min_font:g}px")
                        stem = f"{tag}_{tname}_{name}"
                        r["json"] = f"{stem}.json"
                        (args.output_dir / r["json"]).write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
                        if render:
                            r["png"] = f"{stem}.png"
                            r["render_warnings"] = render(out, ROOT / "brand_kit/assets", args.output_dir / r["png"], max_size=max(w, h))
                            from PIL import Image
                            with Image.open(args.output_dir / r["png"]) as png:
                                r["render_size"] = list(png.size)
                            if r["render_size"] != [w, h]:
                                r["problems"].append("render dimensions differ from target")
                    except Exception as exc:  # noqa: BLE001 - one broken case must not abort the report
                        r["elapsed_ms"] = (time.perf_counter() - started) * 1000
                        r["problems"].append(f"{type(exc).__name__}: {exc}")
                    finally:
                        source, target = original, target_before
                    q = r.get("metrics", {})
                    bad += bool(r["problems"] or r["quality_problems"]) and name not in args.reference_pipelines
                    records.append(r)
                    print(f"{tag:42} {tname:18} {name:10} {r.get('score', 0):7.2f} {q.get('min_font', 0):7.2f} "
                          f"{q.get('below_6px', 0):3} {q.get('text_overflows', 0):4} {q.get('overlap_pairs', 0):4} "
                          f"{q.get('fidelity_violations', 0):4} {r['elapsed_ms']:7.0f}  {'; '.join((r['problems'] + r['quality_problems'])[:2])}", flush=True)
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "real_renderer": bool(render), "schema_checked": bool(schema_validator),
              "gates": {"strict_quality": args.strict_quality, "min_font": args.min_font,
                        "reference_pipelines": args.reference_pipelines},
              "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              "code_hashes": code_hashes,
              "packages": {p: importlib.metadata.version(p) for p in ("Pillow", "skia-python", "cr-renderer")
                           if importlib.util.find_spec({"Pillow": "PIL", "skia-python": "skia", "cr-renderer": "cr_renderer"}[p])},
              "summary": summarize(records), "cases": records, "failed_cases": bad}
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    write_html(args.output_dir, records, source_pngs)
    print(f"\nGated failures: {bad}. Report: {args.output_dir / 'index.html'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
