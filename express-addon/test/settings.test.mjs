import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEFAULT_BACKEND_URL } from "../src/lib/api-client.js";
import { loadBackendUrl, saveBackendUrl } from "../src/lib/settings.js";

function memoryStorage() {
    const data = new Map();
    return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)) };
}

describe("backend URL settings", () => {
    it("round-trips through storage", () => {
        const storage = memoryStorage();
        assert.equal(loadBackendUrl(storage), DEFAULT_BACKEND_URL);
        saveBackendUrl("http://127.0.0.1:9000", storage);
        assert.equal(loadBackendUrl(storage), "http://127.0.0.1:9000");
    });

    it("falls back when storage is missing or throws", () => {
        const throwing = {
            getItem() {
                throw new Error("SecurityError");
            },
            setItem() {
                throw new Error("SecurityError");
            }
        };
        assert.equal(loadBackendUrl(null), DEFAULT_BACKEND_URL);
        assert.equal(loadBackendUrl(throwing), DEFAULT_BACKEND_URL);
        assert.doesNotThrow(() => saveBackendUrl("http://x", throwing));
    });
});
