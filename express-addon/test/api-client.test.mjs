import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError, ChameleonClient, DEFAULT_BACKEND_URL, normalizeBaseUrl } from "../src/lib/api-client.js";

/** Fake fetch that records calls and answers from a route table: "METHOD /path" -> [status, body|text]. */
function fakeFetch(routes) {
    const calls = [];
    const impl = async (url, init) => {
        const { pathname } = new URL(url);
        calls.push({ url, method: init.method, headers: init.headers, body: init.body === undefined ? undefined : JSON.parse(init.body) });
        const route = routes[`${init.method} ${pathname}`];
        if (route instanceof Error) {
            throw route;
        }
        if (!route) {
            return new Response(JSON.stringify({ error: `unknown endpoint ${pathname}` }), { status: 404 });
        }
        const [status, body] = route;
        return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
    };
    return { impl, calls };
}

describe("normalizeBaseUrl", () => {
    it("adds http:// to bare hosts and strips trailing slashes", () => {
        assert.equal(normalizeBaseUrl("localhost:8765"), "http://localhost:8765");
        assert.equal(normalizeBaseUrl("  http://127.0.0.1:8765/ "), "http://127.0.0.1:8765");
        assert.equal(normalizeBaseUrl("https://example.com/chameleon//"), "https://example.com/chameleon");
    });

    it("rejects empty, non-http and decorated URLs", () => {
        for (const bad of ["", "   ", "ftp://host", "javascript:alert(1)", "http://host/?q=1", "http://u:p@host", "http://"]) {
            assert.throws(() => normalizeBaseUrl(bad), ApiError, bad);
        }
    });

    it("defaults to the documented local backend", () => {
        assert.equal(new ChameleonClient(undefined, { fetch: async () => {} }).baseUrl, DEFAULT_BACKEND_URL);
    });
});

describe("ChameleonClient", () => {
    it("reports health without throwing", async () => {
        const up = fakeFetch({ "GET /api/health": [200, { ok: true }] });
        assert.equal(await new ChameleonClient("localhost:8765", { fetch: up.impl }).isHealthy(), true);
        assert.equal(up.calls[0].url, "http://localhost:8765/api/health");

        const notOk = fakeFetch({ "GET /api/health": [200, { ok: false }] });
        assert.equal(await new ChameleonClient("localhost:8765", { fetch: notOk.impl }).isHealthy(), false);

        const down = fakeFetch({ "GET /api/health": new TypeError("Failed to fetch") });
        assert.equal(await new ChameleonClient("localhost:8765", { fetch: down.impl }).isHealthy(), false);
    });

    it("unwraps formats, pipelines and samples", async () => {
        const format = { key: "instagram_post", label: "Instagram Post", width: 1080, height: 1080 };
        const sample = { name: "a.json", dir: "input", task_id: "a", canvas: { width: 10, height: 10 } };
        const { impl } = fakeFetch({
            "GET /api/formats": [200, { formats: [format] }],
            "GET /api/pipelines": [200, { pipelines: ["anchored", "flow"], default: "flow" }],
            "GET /api/samples": [200, { samples: [sample] }]
        });
        const client = new ChameleonClient("http://localhost:8765", { fetch: impl });
        assert.deepEqual(await client.formats(), [format]);
        assert.deepEqual(await client.pipelines(), { pipelines: ["anchored", "flow"], default: "flow" });
        assert.deepEqual(await client.samples(), [sample]);
    });

    it("rejects malformed list responses", async () => {
        const { impl } = fakeFetch({ "GET /api/formats": [200, { formats: "nope" }] });
        await assert.rejects(new ChameleonClient("localhost:1", { fetch: impl }).formats(), /not a list/);
    });

    it("URL-encodes sample path segments", async () => {
        const { impl, calls } = fakeFetch({ "GET /api/samples/input/my%20task.json": [200, { source: {} }] });
        await new ChameleonClient("localhost:1", { fetch: impl }).sample("input", "my task.json");
        assert.equal(calls[0].url, "http://localhost:1/api/samples/input/my%20task.json");
    });

    it("posts source + target_canvas (+ pipeline) to /api/resize", async () => {
        const payload = { output: { canvas: { width: 5, height: 6 }, elements: [] }, validation: [] };
        const { impl, calls } = fakeFetch({ "POST /api/resize": [200, payload] });
        const client = new ChameleonClient("localhost:8765", { fetch: impl });
        const source = { canvas: { width: 10, height: 10 }, elements: [{ id: "a" }] };

        assert.deepEqual(await client.resize({ source, targetCanvas: { width: 5, height: 6 }, pipeline: "flow" }), payload);
        assert.deepEqual(calls[0].body, { source, target_canvas: { width: 5, height: 6 }, pipeline: "flow" });
        assert.equal(calls[0].headers["Content-Type"], "application/json");

        await client.resize({ task: { source, target_canvas: { width: 1, height: 1 } } });
        assert.deepEqual(calls[1].body, { task: { source, target_canvas: { width: 1, height: 1 } } });
        assert.equal("pipeline" in calls[1].body, false);
    });

    it("requires a task or a source with a target", async () => {
        const client = new ChameleonClient("localhost:1", { fetch: async () => assert.fail("must not fetch") });
        await assert.rejects(client.resize({ source: {} }), ApiError);
        await assert.rejects(client.resize(), ApiError);
    });

    it("surfaces backend error messages with the HTTP status", async () => {
        const { impl } = fakeFetch({ "POST /api/resize": [400, { error: "target canvas must be positive" }] });
        const error = await new ChameleonClient("localhost:1", { fetch: impl })
            .resize({ source: {}, targetCanvas: { width: 0, height: 0 } })
            .catch((e) => e);
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 400);
        assert.match(error.message, /target canvas must be positive/);
    });

    it("reports non-JSON and network failures as ApiError", async () => {
        const html = fakeFetch({ "GET /api/formats": [502, "<html>Bad Gateway</html>"] });
        await assert.rejects(new ChameleonClient("localhost:1", { fetch: html.impl }).formats(), (e) => e instanceof ApiError && e.status === 502);

        const down = fakeFetch({ "GET /api/samples": new TypeError("Failed to fetch") });
        await assert.rejects(new ChameleonClient("localhost:1", { fetch: down.impl }).samples(), (e) => e instanceof ApiError && /reachable/.test(e.message));
    });

    it("times out hung requests", async () => {
        const hang = (url, init) =>
            new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
        const client = new ChameleonClient("localhost:1", { fetch: hang });
        await assert.rejects(client._request("GET", "/api/formats", { timeoutMs: 20 }), /timed out/);
    });
});
