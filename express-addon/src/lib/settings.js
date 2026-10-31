/**
 * Persist the backend URL across panel reloads. localStorage can be unavailable or throw
 * inside sandboxed iframes, so every access is guarded and falls back to the default.
 */
import { DEFAULT_BACKEND_URL } from "./api-client.js";

const STORAGE_KEY = "chameleon.backendUrl";

export function loadBackendUrl(storage = safeStorage()) {
    try {
        return storage?.getItem(STORAGE_KEY) || DEFAULT_BACKEND_URL;
    } catch {
        return DEFAULT_BACKEND_URL;
    }
}

export function saveBackendUrl(url, storage = safeStorage()) {
    try {
        storage?.setItem(STORAGE_KEY, url);
    } catch {
        // Non-fatal: the URL just will not survive a reload.
    }
}

function safeStorage() {
    try {
        return globalThis.localStorage ?? null;
    } catch {
        return null;
    }
}
