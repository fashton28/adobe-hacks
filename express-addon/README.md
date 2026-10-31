# CHAMELEON - Adobe Express add-on

An Adobe Express panel add-on that adapts a design to another format with the CHAMELEON engine and inserts the rendered result into the current Express page.
It is a thin client: all resizing, validation and rendering happen in the local CHAMELEON viewer backend (`webapp/`, `python -m webapp`), which the panel calls over HTTP.

## What the panel does

1. Connects to the backend URL (default `http://localhost:8765`, editable, remembered in `localStorage`) and shows a connection status light.
2. Lets you pick a sample task served by the backend, or upload a task JSON (`{source, target_canvas?}` or a bare `{canvas, elements}` design).
3. Lets you pick the target format: the task's own `target_canvas` (if present) plus the shared catalogue from `pipelines/common/formats.py` (served by `GET /api/formats`), and optionally a pipeline.
4. **Run** calls `POST /api/resize` and shows the rendered output (toggle to the source rendering), pass/fail validation with the list of problems, minimum font size, text overflows, overlaps, elapsed time, the pipeline's internal heuristic score, and renderer warnings such as missing assets.
5. **Add to page** decodes the rendered output PNG and inserts it with `addOnUISdk.app.document.addImage(blob, {title})`.
6. **Add all formats** resizes the task to every catalogue format in turn and inserts each rendering.

The panel never edits element content, fonts or asset pixels; it only displays and inserts what the backend renders.

## Project layout

```
express-addon/
  package.json            scripts: build, start, package (Adobe CLI), test, lint, check
  webpack.config.cjs      template webpack config (renamed to .cjs because the package is ESM)
  eslint.config.mjs       ESLint flat config
  src/
    manifest.json         add-on manifest (manifestVersion 2, one panel entry point)
    index.html, index.js  panel entry
    components/
      chameleon-panel.js  Lit element using Spectrum Web Components (Express theme)
      panel-styles.js     layout CSS on top of Spectrum tokens
    lib/
      api-client.js       backend client (injectable fetch, timeouts, ApiError)
      task.js             task parsing, format options, result summary, data URL -> Blob
      settings.js         guarded localStorage for the backend URL
      sdk.js              loads the Add-on UI SDK; resolves null outside Express
  test/                   node:test unit tests for everything in src/lib
```

The project was generated with the official CLI (`npx @adobe/create-ccweb-add-on chameleon --template swc-javascript`, CLI version 3.11.0) and then adapted.
Changes from the template: Lit 3 instead of Lit 2 (the template's Lit 2 plus Spectrum's `@lit-labs/observers` loaded two Lit runtimes), no decorators (so ESLint parses the sources without Babel), `"type": "module"` with `webpack.config.cjs`, and added unit tests and linting.

## Requirements

- Node.js 22 or newer (verified with Node 24.19.0 and npm 11.17.0).
- The repository's Python environment, to run the backend (`.venv/bin/python -m webapp`).
- An Adobe account with access to Adobe Express, and a desktop browser.
  Chrome is what this README's steps were written against; other browsers are not verified.

## Commands

Run these inside `express-addon/`.

| Command | What it does |
| --- | --- |
| `npm install` | Install dependencies. |
| `npm run build` | Build into `dist/` (`index.html`, `index.js`, `manifest.json`, chunks). |
| `npm run start` | Build and serve `dist/` at `https://localhost:5241` for Adobe Express. |
| `npm test` | Unit tests (`node --test`), no browser needed. |
| `npm run lint` | ESLint. |
| `npm run check` | Lint, test and build. |
| `npm run package` | Production build (`NODE_ENV=production`, minified, Lit and Spectrum production builds) into `dist/`, zipped to `dist.zip` (not needed for local testing). |

## Load the add-on in Adobe Express (step by step)

These steps require your Adobe login, so they were not performed by the agent that wrote this add-on.
UI labels come from the Adobe docs and CLI README cited below; Adobe occasionally renames them.

1. Start the backend from the repository root and leave it running:
   ```sh
   .venv/bin/python -m webapp
   ```
   It prints `CHAMELEON viewer running at http://localhost:8765` and listens on both `127.0.0.1` and `::1`.
   Check it with `curl http://localhost:8765/api/health`, which should print `{"ok": true}`.
2. In a second terminal, install and build the add-on:
   ```sh
   cd express-addon
   npm install
   npm run build
   ```
3. Start the add-on dev server:
   ```sh
   npm run start
   ```
   The first time, the CLI says "The Add-on requires a trusted SSL certificate in order to run on https://localhost" and asks "How do you want to set up your SSL certificate".
   Choose "Automatically, set it up for me"; it installs a locally trusted certificate and may ask for your macOS password.
   When it is ready it prints a link to `https://www.adobe.com/go/addon-cli` and serves the add-on at `https://localhost:5241`.
4. Open Adobe Express in Chrome (`https://new.express.adobe.com`) and sign in.
5. Enable add-on development once: open your avatar menu, go to **Settings**, and turn on **Add-on Development** in the **General** tab.
   If the switch is greyed out, click **Accept and Enable** to accept the Adobe Developer Terms of Use first.
   (The dev-tooling docs describe the same switch inside the **Add-ons** panel.)
6. Create or open any design.
7. Click the **Add-ons** icon in the left rail, open the **Your add-ons** tab, and turn on **Add-on testing** (labelled **Test your local add-on** in some versions).
8. In the **Connect to development server** dialog keep the default `https://localhost:5241`, tick the checkbox, and click **Connect**.
9. If Chrome asks whether Adobe Express may access devices on your local network, click **Allow**.
   Chrome 142 and later require this for local add-on development (see the Adobe FAQ below), and the panel also needs it to reach the backend.
10. Open **CHAMELEON** from the add-ons list (under in-development add-ons).
11. In the panel, check that the status light says **Connected**.
    If your backend runs elsewhere, edit **Backend URL**, then press Enter or click **Connect**.
12. Pick a design and a target format, click **Run**, review the preview, validation and metrics, then click **Add to page** (or **Add all formats**).

Code changes rebuild and reload in Express automatically while `npm run start` is running.

## Network, CORS and mixed content

- **Manifest permissions.**
  The manifest v2 `entryPoints[].permissions` object only supports `sandbox`, `oauth`, `clipboard`, `microphone` and `camera`.
  There is no network or allowed-domains permission (the reference page has none, and the CLI's manifest validator in `@adobe/ccweb-add-on-manifest` knows no other keys).
  This add-on needs none of them: it uses `fetch` and `addImage` only, opens no popups, writes no clipboard and downloads nothing.
- **CORS.**
  The panel runs in a sandboxed iframe on its own origin: `https://localhost:5241` in development, and a unique `https://<add-on-id>.wxp.adobe-addons.com` subdomain once published.
  Requests to the backend are therefore cross-origin.
  The backend answers every request with `Access-Control-Allow-Origin: *` and handles `OPTIONS` preflights, which covers both origins.
  The rendered PNGs come back as `data:` URLs inside the JSON, so the cross-origin isolation headers on add-on resources (COEP is `credentialless`, and Adobe says it will become `require-corp`) do not affect image loading.
- **Mixed content.**
  The panel is an `https` page calling an `http` backend.
  Browsers treat `http://localhost` and `http://127.0.0.1` as potentially trustworthy (W3C Secure Contexts), so Chrome and Firefox do not block these calls as mixed content.
  A plain-`http` backend on any other host (for example `http://192.168.1.20:8765`) would be blocked; serve it over `https` instead.
  Safari's handling was not verified.
- **Local Network Access.**
  Chrome 142 and later ask for permission before a public site reaches `localhost`.
  If you dismissed the prompt, re-enable it via the site settings icon in Chrome's address bar for `new.express.adobe.com`.
- **`localhost` vs `127.0.0.1`.**
  By default the backend listens on both loopback addresses, `127.0.0.1` and `::1`, so `http://localhost:8765` works whichever one the browser resolves `localhost` to.
  If you start it with an explicit `--host`, use a Backend URL that matches that address.
- **Publishing.**
  This add-on is meant for local development and demos.
  A published add-on could not assume a backend on the user's machine; it would need the backend hosted on `https`.

## Preview outside Express

You can check the panel in a normal browser without Adobe Express; only **Add to page** and **Add all formats** stay disabled ("Open this panel inside Adobe Express to add images to a page").

```sh
.venv/bin/python -m webapp --port 8765 &
.venv/bin/python -m http.server 8798 --bind 127.0.0.1 --directory express-addon/dist &
open http://localhost:8798/index.html
```

Narrow the window to about 320 px to match the Express panel width.

## Production build and dependency audit

`npm run package` is the production build.
It compiles with webpack in production mode, which resolves the production (non-`development`) builds of Lit and Spectrum Web Components, so the panel logs no dev-mode warnings, and webpack itself reports no warnings.
The main bundle is about 670 KiB minified, most of it the Spectrum Express theme CSS.
Only the Express theme fragments are imported, because `<sp-theme system="express">` never reads the default Spectrum ones.
`webpack.config.cjs` sets a 768 KiB production size budget that fails the build if the bundle grows past it, instead of webpack's generic 244 KiB hint that no Spectrum panel can meet.

`npm audit --omit=dev` reports 0 vulnerabilities: nothing that ships in the panel bundle is affected.
Patched versions of the Adobe CLI's vulnerable transitive dependencies (`express`, `body-parser`, `path-to-regexp`, `qs`, `ws`, `axios`, `tmp`, `adm-zip`) are forced with `overrides` in `package.json`; all are within the same release line as the versions the CLI pins.
The remaining finding (checked on 2026-10-30) is a moderate `minimatch` advisory reached only through ESLint and the Adobe CLI's `@oclif/core`, `glob` and `jake`.
These are developer tools that run on your machine against your own files, and `npm audit` offers no fix other than downgrading ESLint to 4.x, so they stay.

## Tests

`npm test` covers the API client (URL normalization, every endpoint, request bodies, backend error messages, non-JSON and network failures, timeouts), task parsing and validation, target option building, result summaries, data URL decoding, and settings persistence.
The Lit component itself has no automated test in this package; it was checked in headless Chromium against the real backend (see [Verification status](#verification-status)).

## Verification status

Verified locally (Node 24.19.0, macOS):

- `npm install`, `npm run lint`, `npm test` (25 tests) and `npm run build` succeed, and `dist/` contains `manifest.json`, `index.html` and `index.js`.
- `npm run package` builds the production bundle with no webpack warnings and writes `dist.zip`.
  In headless Chromium at 320 px the production build loads with no console warnings or errors, connects to `http://localhost:<port>`, runs a resize, opens the target format picker, and passes a PNG blob to a stubbed `addImage`.
- In headless Chromium at 320 px, the built panel connects to a running `python -m webapp` over `http://localhost`, loads samples, formats and pipelines, runs a resize, shows the preview, validation and metrics, accepts an uploaded task JSON, switches target format through the picker, and calls `addImage` once for **Add to page** and 13 times for **Add all formats** with PNG blobs.
  `addImage` was a stub there, because the real SDK only works inside Express.

Not verified:

- Loading the add-on inside Adobe Express (needs an Adobe login), including the real `addImage` call, Express's iframe sandbox, and the Chrome Local Network Access prompt.
- `npm run start` with a trusted certificate (the SSL setup is interactive and installs a certificate on the machine).
- Browsers other than Chromium.

## Sources

Adobe Express add-on documentation, consulted on 2026-10-30:

- Manifest reference (manifestVersion 2, entry points, permissions): https://developer.adobe.com/express/add-ons/docs/references/manifest/
- Development tools (CLI templates, `npm run build` / `npm run start`, port 5241, loading the add-on): https://developer.adobe.com/express/add-ons/docs/guides/getting-started/local-development/dev-tooling
- Add-on UI SDK `addImage` (signature, supported formats, size limits, SDK import): https://developer.adobe.com/express/add-ons/docs/references/addonsdk/app-document
- Iframe runtime context and security (sandbox flags, add-on subdomain, COEP, CORP, CORS): https://developer.adobe.com/express/add-ons/docs/guides/learn/platform_concepts/context
- FAQ (Chrome 142 Local Network Access prompt, custom port, CORS): https://developer.adobe.com/express/add-ons/docs/guides/support/faq
- CLI README (commands, Settings > General > Add-on Development, Your add-ons > Add-on testing): https://github.com/adobe/create-ccweb-add-on
- Quickstart (enable add-on development, Accept and Enable): https://developer.adobe.com/express/add-ons/docs/guides/getting_started/quickstart
- CORS guide: https://developer.adobe.com/express/add-ons/docs/guides/develop/cors

The quickstart and CORS guide returned HTTP 404 when fetched directly; their content was read from search-result summaries.
The scaffold command and SSL prompt were confirmed by actually running `@adobe/create-ccweb-add-on` 3.11.0.
