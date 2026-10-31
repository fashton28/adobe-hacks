import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    TASK_TARGET_KEY,
    dataUrlToBlob,
    formatDimensions,
    formatNumber,
    imageTitle,
    parseTaskText,
    summarizeResult,
    targetOptions
} from "../src/lib/task.js";

const SOURCE = { canvas: { width: 1080, height: 1080 }, elements: [{ id: "bg", type: "shape" }] };

describe("parseTaskText", () => {
    it("accepts a full task", () => {
        const task = parseTaskText(JSON.stringify({ task_id: "t1", source: SOURCE, target_canvas: { width: 1920, height: 1080 } }));
        assert.deepEqual(task, { source: SOURCE, target_canvas: { width: 1920, height: 1080 }, task_id: "t1" });
    });

    it("wraps a bare design and allows a missing target", () => {
        assert.deepEqual(parseTaskText(JSON.stringify(SOURCE)), { source: SOURCE, target_canvas: null, task_id: null });
    });

    it("rejects invalid input with a readable message", () => {
        const cases = [
            ["{", /Not valid JSON/],
            ["[]", /JSON object/],
            ["{}", /needs a "source"/],
            [JSON.stringify({ source: { canvas: { width: 0, height: 5 }, elements: [{}] } }), /positive integer/],
            [JSON.stringify({ source: { canvas: { width: 5, height: 5 }, elements: [] } }), /non-empty/],
            [JSON.stringify({ source: SOURCE, target_canvas: { width: 1.5, height: 2 } }), /target_canvas/]
        ];
        for (const [text, pattern] of cases) {
            assert.throws(() => parseTaskText(text), pattern, text);
        }
    });
});

describe("targetOptions", () => {
    const formats = [
        { key: "story", label: "Story", width: 1080, height: 1920 },
        { key: "broken", label: "Broken", width: 0, height: 10 }
    ];

    it("puts the task target first and drops invalid formats", () => {
        assert.deepEqual(targetOptions(formats, { width: 300, height: 250 }), [
            { key: TASK_TARGET_KEY, label: "Task target", width: 300, height: 250 },
            { key: "story", label: "Story", width: 1080, height: 1920 }
        ]);
        assert.deepEqual(
            targetOptions(formats, null).map((o) => o.key),
            ["story"]
        );
        assert.deepEqual(targetOptions(undefined, undefined), []);
    });
});

describe("summarizeResult", () => {
    it("extracts key metrics from a passing result", () => {
        const summary = summarizeResult({
            validation: [],
            warnings: ["missing asset logo.png"],
            metrics: { min_font: 14.25, text_overflows: 0, overlap_pairs: 1, texts: [{}] },
            score: 87.5,
            pipeline: "flow",
            elapsed_ms: 42
        });
        assert.deepEqual(summary, {
            passed: true,
            validation: [],
            warnings: ["missing asset logo.png"],
            pipeline: "flow",
            score: 87.5,
            elapsedMs: 42,
            minFont: 14.25,
            textOverflows: 0,
            overlapPairs: 1,
            hasMetrics: true
        });
    });

    it("handles failing results with empty metrics and null score", () => {
        const summary = summarizeResult({ validation: ["canvas does not match target"], metrics: {}, score: null });
        assert.equal(summary.passed, false);
        assert.deepEqual(summary.validation, ["canvas does not match target"]);
        assert.equal(summary.score, null);
        assert.equal(summary.minFont, null);
        assert.equal(summary.hasMetrics, false);
    });

    it("hides min font for designs without text", () => {
        assert.equal(summarizeResult({ validation: [], metrics: { min_font: 0, texts: [] } }).minFont, null);
    });

    it("tolerates garbage", () => {
        assert.equal(summarizeResult(null).passed, true);
        assert.equal(summarizeResult({ validation: "x", metrics: 3 }).hasMetrics, false);
    });
});

describe("formatting", () => {
    it("formats numbers and dimensions", () => {
        assert.equal(formatNumber(12.345, 1, " px"), "12.3 px");
        assert.equal(formatNumber(null), "-");
        assert.equal(formatNumber(Number.NaN), "-");
        assert.equal(formatDimensions({ width: 1080, height: 1350 }), "1080 x 1350");
        assert.equal(formatDimensions(null), "?");
        assert.equal(
            imageTitle("poster", { label: "Story", width: 1080, height: 1920 }),
            "CHAMELEON - poster - Story (1080 x 1920)"
        );
    });
});

describe("dataUrlToBlob", () => {
    it("decodes base64 PNG data URLs byte-for-byte", async () => {
        const bytes = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff]);
        const url = `data:image/png;base64,${Buffer.from(bytes).toString("base64")}`;
        const blob = dataUrlToBlob(url);
        assert.equal(blob.type, "image/png");
        assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes);
    });

    it("rejects non-base64 or non-data URLs", () => {
        assert.throws(() => dataUrlToBlob("https://example.com/a.png"), /data: URL/);
        assert.throws(() => dataUrlToBlob("data:image/png,raw"), /data: URL/);
        assert.throws(() => dataUrlToBlob(undefined), /data: URL/);
    });
});
