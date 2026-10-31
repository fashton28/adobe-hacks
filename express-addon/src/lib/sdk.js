/**
 * Load the Adobe Express Add-on UI SDK without making the panel depend on it.
 *
 * Inside Express, `addOnUISdk.ready` resolves and document APIs become available.
 * Opened as a plain web page (local preview), the SDK either fails to load or never becomes
 * ready; the panel then still works against the backend, only "Add to page" is disabled.
 */
export const SDK_URL = "https://new.express.adobe.com/static/add-on-sdk/sdk.js";

const READY_TIMEOUT_MS = 10000;

/** @returns {Promise<object|null>} the ready addOnUISdk, or null when not running inside Express */
export async function loadAddOnUISdk(timeoutMs = READY_TIMEOUT_MS) {
    let timer;
    const timeout = new Promise((resolve) => {
        timer = setTimeout(() => resolve(null), timeoutMs);
    });
    const ready = (async () => {
        const module = await import(/* webpackIgnore: true */ SDK_URL);
        const sdk = module.default;
        await sdk.ready;
        return sdk;
    })().catch((error) => {
        console.warn("Adobe Express Add-on UI SDK unavailable:", error);
        return null;
    });
    try {
        return await Promise.race([ready, timeout]);
    } finally {
        clearTimeout(timer);
    }
}
