/**
 * Pure helpers for task files, target format options and resize results.
 * No DOM or SDK access, so everything here is unit-tested under `node --test`.
 */

/** Option key used for "the target canvas the task file itself declares". */
export const TASK_TARGET_KEY = "__task_target__";

function isPositiveInt(value) {
    return Number.isInteger(value) && value > 0;
}

function isCanvas(value) {
    return value !== null && typeof value === "object" && isPositiveInt(value.width) && isPositiveInt(value.height);
}

/**
 * Parse an uploaded task file. Accepts a full task ({source, target_canvas?}) or a bare
 * design ({canvas, elements}), which is wrapped as {source: design}.
 * @returns {{source: object, target_canvas: object|null, task_id: string|null}}
 */
export function parseTaskText(text) {
    let data;
    try {
        data = JSON.parse(text);
    } catch (error) {
        throw new Error(`Not valid JSON: ${error.message}`, { cause: error });
    }
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("Task file must contain a JSON object");
    }
    const source = data.source ?? (Array.isArray(data.elements) ? data : null);
    if (!source || typeof source !== "object") {
        throw new Error('Task file needs a "source" design (or a bare design with "canvas" and "elements")');
    }
    if (!isCanvas(source.canvas)) {
        throw new Error("source.canvas needs positive integer width and height");
    }
    if (!Array.isArray(source.elements) || source.elements.length === 0) {
        throw new Error("source.elements must be a non-empty list");
    }
    const target = data.target_canvas ?? null;
    if (target !== null && !isCanvas(target)) {
        throw new Error("target_canvas needs positive integer width and height");
    }
    const taskId = typeof data.task_id === "string" ? data.task_id : null;
    return { source, target_canvas: target, task_id: taskId };
}

/** "1080 x 1350" */
export function formatDimensions(canvas) {
    return isCanvas(canvas) ? `${canvas.width} x ${canvas.height}` : "?";
}

/**
 * Build the target format picker options: the task's own target (if any) first, then the catalogue.
 * @returns {Array<{key: string, label: string, width: number, height: number}>}
 */
export function targetOptions(formats, taskTarget) {
    const options = [];
    if (isCanvas(taskTarget)) {
        options.push({ key: TASK_TARGET_KEY, label: "Task target", width: taskTarget.width, height: taskTarget.height });
    }
    for (const format of formats ?? []) {
        if (format && typeof format.key === "string" && isCanvas(format)) {
            options.push({ key: format.key, label: String(format.label ?? format.key), width: format.width, height: format.height });
        }
    }
    return options;
}

/** Condense a /api/resize payload into what the panel shows. */
export function summarizeResult(result) {
    const validation = Array.isArray(result?.validation) ? result.validation.map(String) : [];
    const warnings = Array.isArray(result?.warnings) ? result.warnings.map(String) : [];
    const metrics = result?.metrics && typeof result.metrics === "object" ? result.metrics : {};
    const finite = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
    const textCount = Array.isArray(metrics.texts) ? metrics.texts.length : null;
    return {
        passed: validation.length === 0,
        validation,
        warnings,
        pipeline: typeof result?.pipeline === "string" ? result.pipeline : null,
        score: finite(result?.score),
        elapsedMs: finite(result?.elapsed_ms),
        // A design without text has no meaningful minimum font size.
        minFont: textCount === 0 ? null : finite(metrics.min_font),
        textOverflows: finite(metrics.text_overflows),
        overlapPairs: finite(metrics.overlap_pairs),
        hasMetrics: Object.keys(metrics).length > 0
    };
}

/** Format a number with fixed decimals, or "-" when missing. */
export function formatNumber(value, decimals = 0, suffix = "") {
    return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(decimals)}${suffix}` : "-";
}

/**
 * Decode a base64 `data:` URL (as returned in source_png / output_png) into a Blob.
 * Decoding locally avoids depending on fetch() support for data: URLs inside the iframe.
 */
export function dataUrlToBlob(dataUrl) {
    const match = /^data:([^;,]+)((?:;[^;,]+)*);base64,(.*)$/s.exec(String(dataUrl ?? ""));
    if (!match) {
        throw new Error("Expected a base64 data: URL");
    }
    const binary = atob(match[3]);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: match[1] });
}

/** Title used for images inserted into the Express document. */
export function imageTitle(taskName, option) {
    const size = formatDimensions(option);
    return `CHAMELEON - ${taskName || "task"} - ${option?.label ?? "target"} (${size})`;
}
