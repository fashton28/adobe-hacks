// Only the Express theme fragments: <sp-theme system="express"> never reads the default
// Spectrum ones, and they would add about 300 KiB of unused CSS to the bundle.
import "@spectrum-web-components/theme/express/scale-medium.js";
import "@spectrum-web-components/theme/express/theme-light.js";
import "@spectrum-web-components/theme/sp-theme.js";

import "@spectrum-web-components/action-button/sp-action-button.js";
import "@spectrum-web-components/button/sp-button.js";
import "@spectrum-web-components/divider/sp-divider.js";
import "@spectrum-web-components/field-label/sp-field-label.js";
import "@spectrum-web-components/help-text/sp-help-text.js";
import "@spectrum-web-components/menu/sp-menu-divider.js";
import "@spectrum-web-components/menu/sp-menu-group.js";
import "@spectrum-web-components/menu/sp-menu-item.js";
import "@spectrum-web-components/picker/sp-picker.js";
import "@spectrum-web-components/progress-circle/sp-progress-circle.js";
import "@spectrum-web-components/status-light/sp-status-light.js";
import "@spectrum-web-components/textfield/sp-textfield.js";

import { LitElement, html, nothing } from "lit";

import { ChameleonClient, normalizeBaseUrl } from "../lib/api-client.js";
import { loadAddOnUISdk } from "../lib/sdk.js";
import { loadBackendUrl, saveBackendUrl } from "../lib/settings.js";
import {
    TASK_TARGET_KEY,
    dataUrlToBlob,
    formatDimensions,
    formatNumber,
    imageTitle,
    parseTaskText,
    summarizeResult,
    targetOptions
} from "../lib/task.js";
import { panelStyles } from "./panel-styles.js";

const UPLOAD_KEY = "__upload__";
const SAMPLE_GROUP_LABELS = { input: "Examples", fixtures: "Fixtures", heldout: "Held-out" };

function sampleGroupLabel(dir) {
    return SAMPLE_GROUP_LABELS[dir] ?? dir.replace(/^heldout(\d+)$/, "Held-out $1");
}

function sampleKey(sample) {
    return `${sample.dir}/${sample.name}`;
}

function sampleLabel(sample) {
    const name = sample.task_id || sample.name.replace(/\.json$/i, "");
    return sample.difficulty_label ? `${name} (${sample.difficulty_label})` : name;
}

export class ChameleonPanel extends LitElement {
    static properties = {
        _backendUrl: { state: true },
        _connection: { state: true },
        _connectionError: { state: true },
        _formats: { state: true },
        _pipelines: { state: true },
        _pipeline: { state: true },
        _samples: { state: true },
        _sampleKey: { state: true },
        _task: { state: true },
        _taskName: { state: true },
        _taskError: { state: true },
        _targetKey: { state: true },
        _running: { state: true },
        _result: { state: true },
        _resultTarget: { state: true },
        _view: { state: true },
        _error: { state: true },
        _sdk: { state: true },
        _sdkState: { state: true },
        _adding: { state: true },
        _addStatus: { state: true }
    };

    static styles = panelStyles;

    constructor() {
        super();
        this._backendUrl = loadBackendUrl();
        this._connection = "checking";
        this._connectionError = "";
        this._formats = [];
        this._pipelines = [];
        this._pipeline = "";
        this._samples = [];
        this._sampleKey = "";
        this._task = null;
        this._taskName = "";
        this._taskError = "";
        this._targetKey = "";
        this._running = false;
        this._result = null;
        this._resultTarget = null;
        this._view = "output";
        this._error = "";
        this._sdk = null;
        this._sdkState = "loading";
        this._adding = false;
        this._addStatus = "";
        this._client = null;
        this._loadToken = 0;
        this._connectToken = 0;
    }

    connectedCallback() {
        super.connectedCallback();
        void this._connect();
        void loadAddOnUISdk().then((sdk) => {
            this._sdk = sdk;
            this._sdkState = sdk ? "ready" : "unavailable";
        });
    }

    // ------------------------------------------------------------------ derived state

    get _targets() {
        return targetOptions(this._formats, this._task?.target_canvas ?? null);
    }

    get _selectedTarget() {
        return this._targets.find((option) => option.key === this._targetKey) ?? null;
    }

    /** Uploaded tasks are not picker entries; the picker shows its placeholder and the hint names the file. */
    get _pickerValue() {
        return this._sampleKey === UPLOAD_KEY ? "" : this._sampleKey;
    }

    get _busy() {
        return this._running || this._adding;
    }

    // ------------------------------------------------------------------ backend

    async _connect() {
        const token = ++this._connectToken;
        let client;
        try {
            client = new ChameleonClient(this._backendUrl);
        } catch (error) {
            this._connection = "offline";
            this._connectionError = error.message;
            return;
        }
        this._connection = "checking";
        this._connectionError = "";
        this._error = ""; // A run error from the previous backend is stale once we reconnect.
        const healthy = await client.isHealthy();
        if (token !== this._connectToken) {
            return;
        }
        if (!healthy) {
            this._client = null;
            this._connection = "offline";
            this._connectionError = `No CHAMELEON backend answered at ${client.baseUrl}. Start it with "python -m webapp" in the repository.`;
            return;
        }
        try {
            const [formats, pipelines, samples] = await Promise.all([client.formats(), client.pipelines(), client.samples()]);
            if (token !== this._connectToken) {
                return;
            }
            this._client = client;
            this._formats = formats;
            this._pipelines = pipelines.pipelines;
            if (!this._pipelines.includes(this._pipeline)) {
                this._pipeline = pipelines.default ?? this._pipelines[0] ?? "";
            }
            this._samples = samples;
            this._connection = "connected";
            if (!this._task && samples.length > 0) {
                const preferred = samples.find((sample) => sample.dir === "input") ?? samples[0];
                await this._selectSample(sampleKey(preferred));
            } else {
                this._ensureTarget();
            }
        } catch (error) {
            if (token === this._connectToken) {
                this._connection = "offline";
                this._connectionError = error.message;
            }
        }
    }

    _onUrlChange(event) {
        this._backendUrl = event.target.value;
    }

    _onUrlKeydown(event) {
        if (event.key === "Enter") {
            void this._applyUrl();
        }
    }

    async _applyUrl() {
        try {
            this._backendUrl = normalizeBaseUrl(this._backendUrl);
        } catch (error) {
            this._connection = "offline";
            this._connectionError = error.message;
            return;
        }
        saveBackendUrl(this._backendUrl);
        await this._connect();
    }

    // ------------------------------------------------------------------ inputs

    async _onSampleChange(event) {
        const key = event.target.value;
        if (key === UPLOAD_KEY) {
            // Keep the picker on the current task until a file is actually chosen.
            event.target.value = this._pickerValue;
            this.renderRoot.querySelector("#task-file").click();
            return;
        }
        await this._selectSample(key);
    }

    async _selectSample(key) {
        const sample = this._samples.find((item) => sampleKey(item) === key);
        if (!sample || !this._client) {
            return;
        }
        const token = ++this._loadToken;
        this._sampleKey = key;
        this._taskError = "";
        this._clearResult();
        try {
            const task = parseTaskText(JSON.stringify(await this._client.sample(sample.dir, sample.name)));
            if (token !== this._loadToken) {
                return;
            }
            this._setTask(task, sampleLabel(sample));
        } catch (error) {
            if (token === this._loadToken) {
                this._task = null;
                this._taskError = error.message;
            }
        }
    }

    async _onFileChosen(event) {
        const input = event.target;
        const file = input.files?.[0];
        input.value = "";
        if (!file) {
            return;
        }
        ++this._loadToken;
        this._clearResult();
        try {
            const task = parseTaskText(await file.text());
            this._sampleKey = UPLOAD_KEY;
            this._taskError = "";
            this._setTask(task, task.task_id || file.name.replace(/\.json$/i, ""));
        } catch (error) {
            this._taskError = `${file.name}: ${error.message}`;
        }
    }

    _setTask(task, name) {
        this._task = task;
        this._taskName = name;
        // Prefer the task's own target; otherwise keep the user's last catalogue choice.
        this._targetKey = task.target_canvas ? TASK_TARGET_KEY : this._targetKey;
        this._ensureTarget();
    }

    _ensureTarget() {
        const targets = this._targets;
        if (!targets.some((option) => option.key === this._targetKey)) {
            this._targetKey = targets[0]?.key ?? "";
        }
    }

    _onTargetChange(event) {
        this._targetKey = event.target.value;
        this._clearResult();
    }

    _onPipelineChange(event) {
        this._pipeline = event.target.value;
        this._clearResult();
    }

    _clearResult() {
        this._result = null;
        this._resultTarget = null;
        this._error = "";
        this._addStatus = "";
    }

    // ------------------------------------------------------------------ actions

    async _resizeTo(option) {
        return this._client.resize({
            source: this._task.source,
            targetCanvas: { width: option.width, height: option.height },
            pipeline: this._pipeline || undefined
        });
    }

    async _run() {
        const option = this._selectedTarget;
        if (!this._client || !this._task || !option || this._busy) {
            return;
        }
        this._running = true;
        this._clearResult();
        try {
            this._result = await this._resizeTo(option);
            this._resultTarget = option;
            this._view = "output";
        } catch (error) {
            this._error = error.message;
        } finally {
            this._running = false;
        }
    }

    async _addToPage() {
        if (!this._sdk || !this._result?.output_png || this._busy) {
            return;
        }
        this._adding = true;
        this._addStatus = "";
        try {
            const blob = dataUrlToBlob(this._result.output_png);
            await this._sdk.app.document.addImage(blob, { title: imageTitle(this._taskName, this._resultTarget) });
            this._addStatus = "Added to the page.";
        } catch (error) {
            this._addStatus = `Could not add the image: ${error.message ?? error}`;
        } finally {
            this._adding = false;
        }
    }

    async _addAllFormats() {
        if (!this._sdk || !this._client || !this._task || this._busy) {
            return;
        }
        const formats = this._targets.filter((option) => option.key !== TASK_TARGET_KEY);
        this._adding = true;
        let added = 0;
        try {
            for (const [index, option] of formats.entries()) {
                this._addStatus = `Rendering ${index + 1} of ${formats.length}: ${option.label}...`;
                const result = await this._resizeTo(option);
                await this._sdk.app.document.addImage(dataUrlToBlob(result.output_png), {
                    title: imageTitle(this._taskName, option)
                });
                added += 1;
            }
            this._addStatus = `Added ${added} formats to the page.`;
        } catch (error) {
            this._addStatus = `Stopped after ${added} of ${formats.length} formats: ${error.message ?? error}`;
        } finally {
            this._adding = false;
        }
    }

    // ------------------------------------------------------------------ render

    render() {
        return html`<sp-theme system="express" color="light" scale="medium">
            <main class="panel">
                <header>
                    <h1>CHAMELEON</h1>
                    <p class="subtitle">Adapt a design to any format with the local CHAMELEON engine.</p>
                </header>
                ${this._renderBackend()}
                <sp-divider size="s"></sp-divider>
                ${this._renderInputs()}
                ${this._renderResult()}
            </main>
        </sp-theme>`;
    }

    _renderBackend() {
        const status = {
            checking: ["neutral", "Checking..."],
            connected: ["positive", "Connected"],
            offline: ["negative", "Not connected"]
        }[this._connection];
        return html`<section aria-labelledby="backend-label">
            <div class="row between">
                <sp-field-label id="backend-label" for="backend-url" size="s">Backend URL</sp-field-label>
                <sp-status-light size="s" variant=${status[0]}>${status[1]}</sp-status-light>
            </div>
            <div class="row">
                <sp-textfield
                    id="backend-url"
                    class="grow"
                    size="s"
                    .value=${this._backendUrl}
                    @input=${this._onUrlChange}
                    @keydown=${this._onUrlKeydown}
                    label="Backend URL"
                ></sp-textfield>
                <sp-action-button size="s" @click=${this._applyUrl} ?disabled=${this._connection === "checking"}>
                    ${this._connection === "connected" ? "Refresh" : "Connect"}
                </sp-action-button>
            </div>
            ${this._connectionError
                ? html`<sp-help-text size="s" variant="negative" class="message">${this._connectionError}</sp-help-text>`
                : nothing}
        </section>`;
    }

    _renderSampleMenu() {
        const groups = new Map();
        for (const sample of this._samples) {
            if (!groups.has(sample.dir)) {
                groups.set(sample.dir, []);
            }
            groups.get(sample.dir).push(sample);
        }
        return html`
            <sp-menu-item value=${UPLOAD_KEY}>Upload task JSON...</sp-menu-item>
            ${[...groups.entries()].map(
                ([dir, samples]) => html`<sp-menu-divider></sp-menu-divider>
                    <sp-menu-group>
                        <span slot="header">${sampleGroupLabel(dir)}</span>
                        ${samples.map(
                            (sample) => html`<sp-menu-item value=${sampleKey(sample)}>${sampleLabel(sample)}</sp-menu-item>`
                        )}
                    </sp-menu-group>`
            )}
        `;
    }

    _renderInputs() {
        const disabled = this._connection !== "connected" || this._busy;
        const task = this._task;
        return html`<section>
            <sp-field-label for="task" size="s">Design</sp-field-label>
            <sp-picker
                id="task"
                size="s"
                label="Choose a sample or upload"
                .value=${this._pickerValue}
                @change=${this._onSampleChange}
                ?disabled=${disabled}
            >
                ${this._renderSampleMenu()}
            </sp-picker>
            <input id="task-file" type="file" accept=".json,application/json" hidden @change=${this._onFileChosen} />
            ${task
                ? html`<p class="hint">
                      ${this._sampleKey === UPLOAD_KEY ? html`<strong>${this._taskName}</strong> - ` : nothing}
                      ${formatDimensions(task.source.canvas)}, ${task.source.elements.length} elements
                  </p>`
                : nothing}
            ${this._taskError
                ? html`<sp-help-text size="s" variant="negative" class="message">${this._taskError}</sp-help-text>`
                : nothing}

            <sp-field-label for="target" size="s">Target format</sp-field-label>
            <sp-picker
                id="target"
                size="s"
                label="Choose a format"
                .value=${this._targetKey}
                @change=${this._onTargetChange}
                ?disabled=${disabled || !task}
            >
                ${this._targets.map(
                    (option) =>
                        html`<sp-menu-item value=${option.key}>${option.label} - ${formatDimensions(option)}</sp-menu-item>`
                )}
            </sp-picker>

            ${this._pipelines.length > 1
                ? html`<sp-field-label for="pipeline" size="s">Pipeline</sp-field-label>
                      <sp-picker
                          id="pipeline"
                          size="s"
                          label="Pipeline"
                          .value=${this._pipeline}
                          @change=${this._onPipelineChange}
                          ?disabled=${disabled}
                      >
                          ${this._pipelines.map((name) => html`<sp-menu-item value=${name}>${name}</sp-menu-item>`)}
                      </sp-picker>`
                : nothing}

            <sp-button
                class="full run"
                size="m"
                variant="accent"
                @click=${this._run}
                ?disabled=${disabled || !task || !this._selectedTarget}
            >
                ${this._running ? "Resizing..." : "Run"}
            </sp-button>
            ${this._running
                ? html`<div class="row center"><sp-progress-circle size="s" indeterminate label="Resizing"></sp-progress-circle></div>`
                : nothing}
            ${this._error ? html`<sp-help-text size="s" variant="negative" class="message">${this._error}</sp-help-text>` : nothing}
        </section>`;
    }

    _renderResult() {
        const result = this._result;
        if (!result) {
            return nothing;
        }
        const summary = summarizeResult(result);
        const image = this._view === "source" ? result.source_png : result.output_png;
        const sdkReady = this._sdkState === "ready";
        return html`<sp-divider size="s"></sp-divider>
            <section aria-label="Result">
                <div class="row between">
                    <div class="title">
                        <h2>${this._resultTarget?.label ?? "Result"}</h2>
                        <span class="hint">${formatDimensions(this._resultTarget)}</span>
                    </div>
                    <div class="row tight" role="group" aria-label="Preview">
                        <sp-action-button size="xs" quiet ?selected=${this._view === "output"} @click=${() => (this._view = "output")}>
                            Output
                        </sp-action-button>
                        <sp-action-button size="xs" quiet ?selected=${this._view === "source"} @click=${() => (this._view = "source")}>
                            Source
                        </sp-action-button>
                    </div>
                </div>
                ${image
                    ? html`<div class="preview"><img src=${image} alt=${`${this._view} rendering`} /></div>`
                    : html`<p class="hint">No rendering returned.</p>`}

                <sp-status-light size="s" variant=${summary.passed ? "positive" : "negative"}>
                    ${summary.passed ? "Validation passed" : `Validation failed (${summary.validation.length})`}
                </sp-status-light>
                ${summary.passed
                    ? nothing
                    : html`<ul class="issues">
                          ${summary.validation.map((problem) => html`<li>${problem}</li>`)}
                      </ul>`}

                <dl class="metrics">
                    <div><dt>Min font</dt><dd>${formatNumber(summary.minFont, 1, " px")}</dd></div>
                    <div><dt>Text overflows</dt><dd>${formatNumber(summary.textOverflows)}</dd></div>
                    <div><dt>Overlaps</dt><dd>${formatNumber(summary.overlapPairs)}</dd></div>
                    <div><dt>Elapsed</dt><dd>${formatNumber(summary.elapsedMs, 0, " ms")}</dd></div>
                    <div title="Internal pipeline heuristic, higher is better. Not the official hackathon score."><dt>Heuristic score</dt><dd>${formatNumber(summary.score, 2)}</dd></div>
                    <div><dt>Pipeline</dt><dd>${summary.pipeline ?? "-"}</dd></div>
                </dl>
                ${summary.warnings.map(
                    (warning) => html`<sp-help-text size="s" variant="neutral" class="message">${warning}</sp-help-text>`
                )}

                <sp-button class="full" size="m" variant="accent" @click=${this._addToPage} ?disabled=${!sdkReady || this._busy}>
                    Add to page
                </sp-button>
                <sp-button class="full" size="m" variant="secondary" treatment="outline" @click=${this._addAllFormats} ?disabled=${!sdkReady || this._busy}>
                    Add all formats
                </sp-button>
                ${this._adding
                    ? html`<div class="row center"><sp-progress-circle size="s" indeterminate label="Adding"></sp-progress-circle></div>`
                    : nothing}
                ${this._addStatus ? html`<p class="hint" role="status">${this._addStatus}</p>` : nothing}
                ${this._sdkState === "unavailable"
                    ? html`<sp-help-text size="s" class="message">Open this panel inside Adobe Express to add images to a page.</sp-help-text>`
                    : nothing}
            </section>`;
    }
}

customElements.define("chameleon-panel", ChameleonPanel);
