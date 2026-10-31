/**
 * Minimal client for the local CHAMELEON viewer backend (webapp/, default http://localhost:8765).
 *
 * Pure ES module with an injectable `fetch`, so it runs unchanged in the Express panel iframe,
 * in a plain browser, and under `node --test`.
 */

export const DEFAULT_BACKEND_URL = "http://localhost:8765";

const DEFAULT_TIMEOUT_MS = 8000;
const RESIZE_TIMEOUT_MS = 180000;

/** Error raised for any failed backend call; `status` is the HTTP status or 0 for network/timeout errors. */
export class ApiError extends Error {
    constructor(message, { status = 0, cause } = {}) {
        super(message, cause === undefined ? undefined : { cause });
        this.name = "ApiError";
        this.status = status;
    }
}

/**
 * Normalize a user-typed backend URL to `scheme://host[:port][/path]` without a trailing slash.
 * Bare hosts ("localhost:8765") get `http://`. Throws ApiError for anything that is not http(s).
 */
export function normalizeBaseUrl(raw) {
    const text = String(raw ?? "").trim();
    if (!text) {
        throw new ApiError("Backend URL is empty");
    }
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `http://${text}`;
    let url;
    try {
        url = new URL(withScheme);
    } catch {
        throw new ApiError(`Invalid backend URL: ${text}`);
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
        throw new ApiError(`Backend URL must use http or https: ${text}`);
    }
    if (url.search || url.hash || url.username || url.password) {
        throw new ApiError(`Backend URL must not contain credentials, query or fragment: ${text}`);
    }
    return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
}

export class ChameleonClient {
    /**
     * @param {string} baseUrl backend root, e.g. "http://localhost:8765"
     * @param {{fetch?: typeof fetch}} [options] inject a fetch implementation (tests)
     */
    constructor(baseUrl = DEFAULT_BACKEND_URL, { fetch: fetchImpl } = {}) {
        this.baseUrl = normalizeBaseUrl(baseUrl);
        this._fetch = fetchImpl ?? globalThis.fetch.bind(globalThis);
    }

    /** True when the backend answers GET /api/health with {"ok": true}. Never throws. */
    async isHealthy() {
        try {
            const body = await this._request("GET", "/api/health", { timeoutMs: 4000 });
            return body?.ok === true;
        } catch {
            return false;
        }
    }

    /** @returns {Promise<Array<{key: string, label: string, width: number, height: number}>>} */
    async formats() {
        const body = await this._request("GET", "/api/formats");
        return expectArray(body?.formats, "formats");
    }

    /** @returns {Promise<{pipelines: string[], default: string|null}>} */
    async pipelines() {
        const body = await this._request("GET", "/api/pipelines");
        return { pipelines: expectArray(body?.pipelines, "pipelines"), default: body?.default ?? null };
    }

    /** @returns {Promise<Array<object>>} sample descriptors ({name, dir, task_id, canvas, target_canvas, ...}) */
    async samples() {
        const body = await this._request("GET", "/api/samples");
        return expectArray(body?.samples, "samples");
    }

    /** Fetch one sample task JSON by its `dir` and `name` from samples(). */
    async sample(dir, name) {
        const path = `/api/samples/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`;
        return this._request("GET", path);
    }

    /**
     * Resize a task. Pass either `{task}` or `{source, targetCanvas}`; `pipeline` is optional.
     * Resolves to the backend payload: {output, validation, metrics, score, pipeline, elapsed_ms,
     * warnings, source_png, output_png}.
     */
    async resize({ task, source, targetCanvas, pipeline } = {}) {
        let body;
        if (task !== undefined) {
            body = { task };
        } else if (source !== undefined && targetCanvas !== undefined) {
            body = { source, target_canvas: targetCanvas };
        } else {
            throw new ApiError("resize needs either a task or a source and targetCanvas");
        }
        if (pipeline) {
            body.pipeline = pipeline;
        }
        return this._request("POST", "/api/resize", { body, timeoutMs: RESIZE_TIMEOUT_MS });
    }

    async _request(method, path, { body, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const init = { method, signal: controller.signal, headers: { Accept: "application/json" } };
        if (body !== undefined) {
            init.headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(body);
        }
        let response;
        try {
            response = await this._fetch(`${this.baseUrl}${path}`, init);
        } catch (error) {
            const reason = controller.signal.aborted
                ? `timed out after ${Math.round(timeoutMs / 1000)}s`
                : "is the CHAMELEON backend running and reachable?";
            throw new ApiError(`${method} ${path} failed: ${reason}`, { cause: error });
        } finally {
            clearTimeout(timer);
        }
        const text = await response.text();
        let parsed;
        try {
            parsed = text ? JSON.parse(text) : null;
        } catch (error) {
            throw new ApiError(`${method} ${path}: response is not JSON (HTTP ${response.status})`, {
                status: response.status,
                cause: error
            });
        }
        if (!response.ok) {
            const detail = typeof parsed?.error === "string" ? parsed.error : `HTTP ${response.status}`;
            throw new ApiError(`${method} ${path}: ${detail}`, { status: response.status });
        }
        return parsed;
    }
}

function expectArray(value, name) {
    if (!Array.isArray(value)) {
        throw new ApiError(`Unexpected backend response: "${name}" is not a list`);
    }
    return value;
}
