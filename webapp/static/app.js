/* Chameleon viewer front end. Framework-free; talks to the JSON API in webapp/server.py. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const DIR_LABELS = { input: "Challenge samples", fixtures: "Test fixtures", heldout: "Held-out set" };
  const dirLabel = (dir) => DIR_LABELS[dir] || dir.replace(/^heldout(\d+)$/, "Held-out set $1");
  const MAX_SIDE = 8192;
  const MAX_UPSCALE = 2;
  const STACKED_MIN_STAGE = 160;

  const state = {
    formats: [],
    task: null,          // {source, target_canvas?, task_id?, difficulty_label?}
    taskName: "",        // file stem / file name used for downloads
    origin: "",          // "sample" | "upload"
    result: null,        // last /api/resize payload shown in the Result view
    resultLabel: "",
    runToken: 0,
    abort: null,
    compare: { running: false, cancelled: false, results: [], abort: null },
  };

  const el = {
    health: $("health"),
    sampleSelect: $("sample-select"),
    dropzone: $("dropzone"),
    fileInput: $("file-input"),
    designCard: $("design-card"),
    formats: $("formats"),
    customRadio: $("format-custom"),
    customW: $("custom-w"),
    customH: $("custom-h"),
    pipeline: $("pipeline-select"),
    runBtn: $("run-btn"),
    compareBtn: $("compare-btn"),
    tabResult: $("tab-result"),
    tabCompare: $("tab-compare"),
    viewResult: $("view-result"),
    viewCompare: $("view-compare"),
    errorBanner: $("error-banner"),
    empty: $("empty-state"),
    result: $("result"),
    boxesToggle: $("boxes-toggle"),
    zoom: $("zoom"),
    zoomBoxes: $("zoom-boxes"),
  };

  // ------------------------------------------------------------------ helpers

  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "style") Object.assign(node.style, value);
      else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  function fmt(value, digits = 1) {
    if (!isNum(value)) return "-";
    const rounded = Number(value.toFixed(digits));
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(digits);
  }
  const dims = (c) => (c ? `${c.width} × ${c.height}` : "-");
  const box = (e) => `${fmt(e.width, 0)}×${fmt(e.height, 0)} at ${fmt(e.x, 0)}, ${fmt(e.y, 0)}`;

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let payload = null;
    try { payload = await response.json(); } catch { /* non-JSON body */ }
    if (!response.ok) {
      const message = (payload && payload.error) || `${response.status} ${response.statusText}`;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function showError(title, message) {
    $("error-title").textContent = title;
    $("error-text").textContent = message;
    el.errorBanner.hidden = false;
    // The banner sits at the top of the main column; bring it out from under
    // the sticky top bar when the page is scrolled down (scroll-margin-top).
    el.errorBanner.scrollIntoView({ block: "nearest" });
  }
  function clearError() { el.errorBanner.hidden = true; }

  function download(filename, href) {
    const a = h("a", { href, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
  }

  function safeName(text) {
    return String(text || "design").replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "design";
  }

  // ------------------------------------------------------------------ boot

  async function boot() {
    bindEvents();
    try {
      await api("/api/health");
      setHealth("ok", "Engine online");
    } catch {
      setHealth("down", "Server unreachable");
      showError("Cannot reach the viewer server", "Start it with: .venv/bin/python -m webapp");
      return;
    }
    const [formats, pipelines, samples] = await Promise.allSettled([
      api("/api/formats"), api("/api/pipelines"), api("/api/samples"),
    ]);
    if (formats.status === "fulfilled") {
      state.formats = formats.value.formats;
    } else {
      showError("Could not load formats", formats.reason.message);
    }
    if (pipelines.status === "fulfilled") renderPipelines(pipelines.value);
    else showError("Could not load pipelines", pipelines.reason.message);
    if (samples.status === "fulfilled") renderSamples(samples.value.samples);
    else showError("Could not load samples", samples.reason.message);
    renderFormats();
    updateButtons();
  }

  function setHealth(stateName, label) {
    el.health.dataset.state = stateName;
    el.health.querySelector(".health-label").textContent = label;
  }

  function renderPipelines({ pipelines, default: def }) {
    el.pipeline.replaceChildren(...pipelines.map((name) =>
      h("option", { value: name, selected: name === def }, name === def ? `${name} (default)` : name)));
  }

  function renderSamples(samples) {
    const select = el.sampleSelect;
    select.replaceChildren(h("option", { value: "" }, samples.length ? "Choose a sample..." : "No samples found"));
    const groups = {};
    for (const s of samples) (groups[s.dir] ||= []).push(s);
    for (const [dir, items] of Object.entries(groups)) {
      const group = h("optgroup", { label: dirLabel(dir) });
      for (const s of items) {
        const label = s.difficulty_label ? `${s.difficulty_label.replace(/\s+[\u2014-]\s+/, ": ")}` : s.task_id;
        group.append(h("option", { value: `${s.dir}/${s.name}` }, `${label}  ·  ${dims(s.canvas)}`));
      }
      select.append(group);
    }
  }

  // ------------------------------------------------------------------ formats

  function formatList() {
    const list = state.formats.map((f) => ({ ...f }));
    const t = state.task && state.task.target_canvas;
    if (t && isNum(t.width) && isNum(t.height)) {
      list.unshift({ key: "__task", label: "Task target", width: t.width, height: t.height, task: true });
    }
    return list;
  }

  function renderFormats() {
    const previous = selectedFormatKey();
    const list = formatList();
    el.formats.replaceChildren(...list.map((f) => {
      const scale = 26 / Math.max(f.width, f.height);
      const tw = Math.max(3, Math.round(f.width * scale));
      const th = Math.max(3, Math.round(f.height * scale));
      return h("label", { class: `format${f.task ? " format-task" : ""}`, title: `${f.label} · ${f.width} × ${f.height}` },
        h("input", { type: "radio", name: "format", value: f.key }),
        h("span", { class: "format-body" },
          h("span", { class: "format-thumb", "aria-hidden": "true" }, h("span", { style: { width: `${tw}px`, height: `${th}px` } })),
          h("span", { class: "format-text" },
            h("span", { class: "format-name" }, f.label),
            h("span", { class: "format-dims" }, `${f.width} × ${f.height}`))));
    }));
    const keys = list.map((f) => f.key);
    let pick = keys.includes("__task") && previous !== "custom" ? "__task" : previous;
    if (pick !== "custom" && !keys.includes(pick)) pick = keys[0];
    selectFormat(pick);
  }

  function selectedFormatKey() {
    const checked = document.querySelector('input[name="format"]:checked');
    return checked ? checked.value : null;
  }

  function selectFormat(key) {
    const input = [...document.querySelectorAll('input[name="format"]')].find((i) => i.value === key);
    if (input) input.checked = true;
  }

  function targetCanvas() {
    const key = selectedFormatKey();
    if (key === "custom") {
      const width = Number(el.customW.value);
      const height = Number(el.customH.value);
      if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > MAX_SIDE || height > MAX_SIDE) {
        return { error: `Custom size needs whole numbers between 1 and ${MAX_SIDE}.` };
      }
      return { width, height, label: "Custom" };
    }
    const f = formatList().find((x) => x.key === key);
    return f ? { width: f.width, height: f.height, label: f.label } : { error: "Choose a target format." };
  }

  // ------------------------------------------------------------------ loading designs

  async function loadSample(value) {
    if (!value) return;
    const [dir, name] = value.split("/");
    try {
      const task = await api(`/api/samples/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`);
      setTask(task, name, "sample");
      run();
    } catch (err) {
      showError("Could not load sample", err.message);
    }
  }

  function readFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      let data;
      try {
        data = JSON.parse(String(reader.result));
      } catch (err) {
        showError(`${file.name} is not valid JSON`, err.message);
        return;
      }
      let task = null;
      if (data && typeof data === "object" && data.source && typeof data.source === "object") task = data;
      else if (data && typeof data === "object" && data.canvas && Array.isArray(data.elements)) task = { source: data };
      if (!task) {
        showError(`${file.name} is not a task`, "Expected a task {source, target_canvas} or a design {canvas, elements}.");
        return;
      }
      el.sampleSelect.value = "";
      setTask(task, file.name.replace(/\.json$/i, ""), "upload");
      run();
    };
    reader.onerror = () => showError("Could not read file", String(reader.error));
    reader.readAsText(file);
  }

  function setTask(task, name, origin) {
    clearError();
    state.task = task;
    state.taskName = name;
    state.origin = origin;
    const source = task.source || {};
    $("design-title").textContent = task.task_id || name;
    $("design-origin").textContent = origin === "upload" ? "Uploaded" : "Sample";
    $("design-canvas").textContent = dims(source.canvas);
    $("design-elements").textContent = Array.isArray(source.elements) ? source.elements.length : "-";
    $("design-level").textContent = task.difficulty_label ? task.difficulty_label.split(/\s+[\u2014-]\s+/)[0] : "-";
    $("design-level").title = task.difficulty_label || "";
    el.designCard.hidden = false;
    window.scrollTo({ top: 0 }); // A new design starts at the top of its result.
    stopCompare();
    state.compare.results = [];
    renderCompareGrid();
    renderFormats();
    updateButtons();
  }

  // ------------------------------------------------------------------ running

  function updateButtons() {
    const ready = Boolean(state.task);
    el.runBtn.disabled = !ready || state.compare.running;
    el.compareBtn.disabled = !ready || state.compare.running || !state.formats.length;
  }

  function setRunning(running) {
    el.runBtn.classList.toggle("is-loading", running);
    el.runBtn.querySelector(".btn-label").textContent = running ? "Running..." : "Run resize";
    el.runBtn.setAttribute("aria-busy", String(running));
  }

  function requestBody(target, source = state.task.source) {
    return JSON.stringify({
      source,
      target_canvas: { width: target.width, height: target.height },
      pipeline: el.pipeline.value || undefined,
    });
  }

  async function run() {
    if (!state.task || state.compare.running) return;
    const target = targetCanvas();
    if (target.error) { showError("Invalid target", target.error); return; }
    clearError();
    showView("result");
    if (state.abort) state.abort.abort();
    const controller = new AbortController();
    state.abort = controller;
    const token = ++state.runToken;
    setRunning(true);
    el.runBtn.disabled = true;
    try {
      const result = await api("/api/resize", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: requestBody(target), signal: controller.signal,
      });
      if (token !== state.runToken) return;
      showResult(result, target.label);
    } catch (err) {
      if (err.name === "AbortError" || token !== state.runToken) return;
      clearResult();
      showError(err.status === 400 ? "The design was rejected" : "The engine failed", err.message);
    } finally {
      if (token === state.runToken) {
        setRunning(false);
        updateButtons();
        state.abort = null;
      }
    }
  }

  // ------------------------------------------------------------------ result view

  function showResult(result, label) {
    state.result = result;
    state.resultLabel = label;
    el.empty.hidden = true;
    el.result.hidden = false;
    const out = result.output;
    const source = state.task.source;
    const failed = (result.validation || []).length;

    const badge = $("validation-badge");
    badge.className = `badge ${failed ? "badge-bad" : "badge-ok"}`;
    badge.textContent = failed ? `${failed} validation error${failed > 1 ? "s" : ""}` : "Valid";
    $("summary-title").textContent = `${label} · ${dims(out.canvas)}`;
    $("summary-sub").textContent = `${state.task.task_id || state.taskName} via ${result.pipeline} in ${fmt(result.elapsed_ms, 0)} ms`;

    $("source-dims").textContent = dims(source.canvas);
    $("output-dims").textContent = dims(out.canvas);
    setPreview("source", result.source_png, source);
    setPreview("output", result.output_png, out);

    renderIssues(result);
    renderMetrics(result);
    renderTable(source, out);
  }

  function clearResult() {
    state.result = null;
    el.result.hidden = true;
    el.empty.hidden = false;
  }

  function setPreview(which, src, design) {
    const img = $(`${which}-img`);
    const frame = $(`${which}-frame`);
    img.src = src;
    frame.dataset.w = design.canvas.width;
    frame.dataset.h = design.canvas.height;
    drawOverlay($(`${which}-overlay`), design);
    fitFrame($(`${which}-stage`), frame);
  }

  function fitFrame(stage, frame) {
    const w = Number(frame.dataset.w);
    const hgt = Number(frame.dataset.h);
    if (!w || !hgt) return;
    stage.style.height = "";  // Measure against the stylesheet height first.
    const style = getComputedStyle(stage);
    const padY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const availW = stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const availH = stage.clientHeight - padY;
    const scale = Math.min(availW / w, availH / hgt, MAX_UPSCALE);
    const frameH = Math.max(1, Math.floor(hgt * scale));
    frame.style.width = `${Math.max(1, Math.floor(w * scale))}px`;
    frame.style.height = `${frameH}px`;
    // Stacked previews (narrow screens): shrink the stage to the design so a wide banner
    // does not sit in a tall empty checkerboard. Side by side, both stages keep one height.
    const stacked = getComputedStyle(stage.closest(".previews")).gridTemplateColumns.trim().split(/\s+/).length === 1;
    if (stacked) stage.style.height = `${Math.max(STACKED_MIN_STAGE, Math.ceil(frameH + padY))}px`;
    updateLabels(frame, scale);
  }

  // Hide id labels on boxes too small to carry them; a highlighted box always shows its label.
  function updateLabels(frame, scale) {
    for (const node of frame.querySelectorAll(".box")) {
      const small = Number(node.dataset.w) * scale < 56 || Number(node.dataset.h) * scale < 16;
      node.classList.toggle("no-label", small);
    }
  }

  function drawOverlay(overlay, design) {
    const { width: W, height: H } = design.canvas;
    const boxes = [...design.elements]
      .sort((a, b) => (a.z_index || 0) - (b.z_index || 0))
      .map((e) => h("span", {
        class: "box", dataset: { type: e.type, id: e.id, w: e.width, h: e.height },
        style: {
          left: `${(e.x / W) * 100}%`, top: `${(e.y / H) * 100}%`,
          width: `${(e.width / W) * 100}%`, height: `${(e.height / H) * 100}%`,
          transform: e.rotation ? `rotate(${e.rotation}deg)` : "",
        },
      }, h("span", { class: "box-label" }, e.id)));
    overlay.replaceChildren(...boxes);
  }

  function setBoxes(on) {
    el.boxesToggle.checked = on;
    el.zoomBoxes.checked = on;
    for (const id of ["output-frame", "source-frame", "zoom-frame"]) $(id).classList.toggle("show-boxes", on);
  }

  function highlight(id, on) {
    for (const node of document.querySelectorAll(".box")) {
      node.classList.toggle("is-hot", on && node.dataset.id === id);
    }
  }

  function renderIssues(result) {
    const container = $("issues");
    const cards = [];
    if ((result.validation || []).length) {
      cards.push(h("div", { class: "issue-card issue-bad" },
        h("h3", {}, "Validation failed"),
        h("ul", {}, result.validation.map((v) => h("li", {}, v)))));
    }
    if ((result.warnings || []).length) {
      cards.push(h("div", { class: "issue-card issue-warn" },
        h("h3", {}, `Renderer warnings (${result.warnings.length})`),
        h("ul", {}, result.warnings.map((v) => h("li", {}, v)))));
    }
    container.replaceChildren(...cards);
  }

  function metric(label, value, { unit = "", tone = "", note = "" } = {}) {
    return h("div", { class: "metric", dataset: tone ? { tone } : {} },
      h("span", { class: "metric-label" }, label),
      h("span", { class: "metric-value" }, value, unit ? h("small", {}, unit) : null),
      h("span", { class: "metric-note", title: note || null }, note || " "));
  }

  function renderMetrics(result) {
    const m = result.metrics || {};
    const has = (k) => k in m;
    const minFont = m.min_font;
    const missing = m.missing_assets || [];
    const warnings = result.warnings || [];
    const cards = [
      metric("Score", fmt(result.score, 2), { note: "Local quality proxy, higher is better" }),
      metric("Min font size", has("min_font") ? fmt(minFont, 1) : "-", {
        unit: has("min_font") ? "px" : "",
        tone: !has("min_font") ? "" : minFont < 6 ? "bad" : minFont < 10 ? "warn" : "ok",
        note: has("median_font") ? `Median ${fmt(m.median_font, 1)} px` : "",
      }),
      metric("Text overflows", has("text_overflows") ? fmt(m.text_overflows, 0) : "-", {
        tone: !has("text_overflows") ? "" : m.text_overflows ? "bad" : "ok",
        note: "Copy wider or taller than its box",
      }),
      metric("Overlap severity", has("overlap_severity") ? fmt(m.overlap_severity, 2) : "-", {
        tone: !has("overlap_severity") ? "" : m.overlap_severity > 0.05 ? "bad" : m.overlap_severity > 0 ? "warn" : "ok",
        note: has("overlap_pairs") ? `${m.overlap_pairs} overlapping pair${m.overlap_pairs === 1 ? "" : "s"}` : "",
      }),
      metric("Layout shift", has("layout_shift") ? fmt(m.layout_shift, 3) : "-", { note: "Mean normalized centre drift" }),
      metric("Missing assets", has("missing_assets") ? String(missing.length) : "-", {
        tone: !has("missing_assets") ? "" : missing.length ? "warn" : "ok",
        note: missing.length ? missing.join(", ") : "All assets resolved",
      }),
      metric("Renderer warnings", String(warnings.length), { tone: warnings.length ? "warn" : "ok", note: warnings.length ? "See list above" : "None" }),
      metric("Elapsed", fmt(result.elapsed_ms, 0), { unit: "ms", note: `Pipeline ${result.pipeline}` }),
    ];
    $("metrics").replaceChildren(...cards);
  }

  function renderTable(source, out) {
    const src = Object.fromEntries(source.elements.map((e) => [e.id, e]));
    const rows = [...out.elements]
      .sort((a, b) => (a.z_index || 0) - (b.z_index || 0))
      .map((e) => {
        const s = src[e.id] || {};
        const scale = s.width ? e.width / s.width : s.height ? e.height / s.height : null;
        let font = h("span", { class: "dim" }, "-");
        if (e.type === "text") {
          const before = s.font_size;
          const after = e.font_size;
          const cls = after > before + 0.01 ? "delta-up" : after < before - 0.01 ? "delta-down" : "";
          font = h("span", {}, fmt(before, 1), h("span", { class: "arrow" }, "→"), h("span", { class: cls }, fmt(after, 1)));
        }
        const row = h("tr", { tabindex: "0", dataset: { id: e.id } },
          h("td", { class: "id-cell" }, e.id),
          h("td", {}, h("span", { class: "type-chip", dataset: { type: e.type } }, e.type)),
          h("td", { class: "mono" }, box(s)),
          h("td", { class: "mono" }, box(e)),
          h("td", { class: "num mono" }, scale === null ? "-" : `${fmt(scale, 2)}×`),
          h("td", { class: "num" }, font));
        for (const [type, on] of [["mouseenter", true], ["mouseleave", false], ["focus", true], ["blur", false]]) {
          row.addEventListener(type, () => highlight(e.id, on));
        }
        return row;
      });
    $("elements-table").tBodies[0].replaceChildren(...rows);
  }

  function openZoom(which) {
    if (!state.result) return;
    const design = which === "source" ? state.task.source : state.result.output;
    const src = which === "source" ? state.result.source_png : state.result.output_png;
    const name = which === "source" ? "Source" : "Output";
    $("zoom-title").textContent = `${name} · ${dims(design.canvas)}`;
    $("zoom-img").src = src;
    $("zoom-img").alt = `${name} design`;
    const frame = $("zoom-frame");
    frame.dataset.w = design.canvas.width;
    frame.dataset.h = design.canvas.height;
    drawOverlay($("zoom-overlay"), design);
    frame.classList.toggle("show-boxes", el.boxesToggle.checked);
    el.zoom.showModal();
    applyZoom();
  }

  function applyZoom() {
    const frame = $("zoom-frame");
    const body = $("zoom-body");
    const w = Number(frame.dataset.w);
    const hgt = Number(frame.dataset.h);
    if (!w || !hgt) return;
    const level = document.querySelector('input[name="zoom-level"]:checked').value;
    let scale = Number(level);
    if (level === "fit") {
      const style = getComputedStyle(body);
      const availW = body.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const availH = body.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      scale = Math.min(availW / w, availH / hgt);
    }
    frame.style.width = `${Math.max(1, Math.round(w * scale))}px`;
    frame.style.height = `${Math.max(1, Math.round(hgt * scale))}px`;
    updateLabels(frame, scale);
  }

  // ------------------------------------------------------------------ compare view

  function showView(name) {
    const result = name === "result";
    el.tabResult.setAttribute("aria-selected", String(result));
    el.tabCompare.setAttribute("aria-selected", String(!result));
    el.tabResult.tabIndex = result ? 0 : -1;
    el.tabCompare.tabIndex = result ? -1 : 0;
    el.viewResult.hidden = !result;
    el.viewCompare.hidden = result;
    if (result && state.result) requestAnimationFrame(refit);
  }

  function stopCompare() {
    const c = state.compare;
    c.cancelled = true;
    if (c.abort) c.abort.abort();
  }

  async function compareAll() {
    if (!state.task || state.compare.running) return;
    clearError();
    const formats = state.formats.map((f) => ({ ...f }));
    const pipeline = el.pipeline.value;
    const source = state.task.source;  // Pinned: the design must not change mid-run.
    const c = state.compare;
    c.running = true;
    c.cancelled = false;
    c.pipeline = pipeline;
    const results = formats.map((f) => ({ format: f, status: "queued" }));
    c.results = results;
    updateButtons();
    showView("compare");
    $("compare-cancel").hidden = false;
    $("compare-progress").hidden = false;
    $("compare-title").textContent = `All formats · ${state.task.task_id || state.taskName}`;
    $("compare-sub").textContent = `Pipeline ${pipeline}. Click a result to inspect it.`;
    renderCompareGrid();
    for (let i = 0; i < results.length; i += 1) {
      if (c.cancelled) break;
      const item = results[i];
      item.status = "running";
      updateCompareProgress(i);
      renderCompareCard(i);
      c.abort = new AbortController();
      try {
        item.result = await api("/api/resize", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: requestBody(item.format, source), signal: c.abort.signal,
        });
        item.status = "done";
      } catch (err) {
        item.status = err.name === "AbortError" ? "skipped" : "error";
        item.error = err.message;
      }
      c.abort = null;
      if (c.results !== results) break;  // A new design was loaded; its view is already reset.
      renderCompareCard(i);
    }
    for (const item of results) if (item.status === "queued") item.status = "skipped";
    c.running = false;
    $("compare-cancel").hidden = true;
    updateButtons();
    if (c.results !== results) {
      run();  // A design loaded mid-compare could not run then; show its result now.
      return;
    }
    renderCompareGrid();
    updateCompareProgress(results.filter((r) => r.status === "done" || r.status === "error").length);
  }

  function updateCompareProgress(done) {
    const c = state.compare;
    const total = c.results.length;
    $("compare-bar").style.width = `${total ? (done / total) * 100 : 0}%`;
    const failed = c.results.filter((r) => r.status === "error" || (r.result && (r.result.validation || []).length)).length;
    let label;
    if (c.running) label = `Running ${Math.min(done + 1, total)} of ${total}`;
    else if (c.cancelled) label = `Stopped after ${done} of ${total}`;
    else label = failed ? `${total} done, ${failed} with problems` : `All ${total} formats valid`;
    $("compare-progress-label").textContent = label;
    const count = $("compare-count");
    count.hidden = !total;
    count.textContent = total;
  }

  function renderCompareGrid() {
    const c = state.compare;
    $("compare-empty").hidden = c.results.length > 0;
    if (!c.results.length) {
      $("compare-progress").hidden = true;
      $("compare-count").hidden = true;
      $("compare-title").textContent = "All formats";
      $("compare-sub").textContent = "Run the current design against every catalogue format.";
    }
    $("compare-grid").replaceChildren(...c.results.map((_, i) => compareCard(i)));
  }

  function renderCompareCard(i) {
    const grid = $("compare-grid");
    const old = grid.children[i];
    if (old) old.replaceWith(compareCard(i));
  }

  function compareCard(i) {
    const item = state.compare.results[i];
    const f = item.format;
    const r = item.result;
    let stage;
    if (item.status === "done") stage = h("img", { src: r.output_png, alt: `${f.label} output`, loading: "lazy" });
    else if (item.status === "error") stage = h("span", { class: "card-fail" }, item.error);
    else if (item.status === "skipped") stage = h("span", { class: "card-fail dim" }, "Skipped");
    else {
      const scale = 168 / Math.max(f.width, f.height);
      stage = h("span", {
        class: "card-ghost", role: "img", "aria-label": item.status === "queued" ? "Queued" : "Running",
        style: { width: `${Math.max(8, Math.round(f.width * scale))}px`, height: `${Math.max(8, Math.round(f.height * scale))}px` },
      }, item.status === "running" ? h("span", { class: "card-wait" }) : null);
    }

    let stats;
    if (r) {
      const failed = (r.validation || []).length;
      const m = r.metrics || {};
      stats = [
        h("span", { class: `badge ${failed ? "badge-bad" : "badge-ok"}` }, failed ? `${failed} error${failed > 1 ? "s" : ""}` : "Valid"),
        h("span", { class: "stat" }, `Score ${fmt(r.score, 2)}`),
        h("span", { class: `stat${isNum(m.min_font) && m.min_font < 6 ? " stat-bad" : ""}` }, `Min ${fmt(m.min_font, 1)} px`),
      ];
      if (m.text_overflows) stats.push(h("span", { class: "stat stat-bad" }, `${m.text_overflows} overflow${m.text_overflows > 1 ? "s" : ""}`));
    } else {
      stats = [h("span", { class: "dim" }, item.status === "error" ? "Request failed" : item.status === "skipped" ? "Not run" : item.status === "running" ? "Running..." : "Queued")];
    }
    const card = h("button", { type: "button", class: "card", disabled: !r, "aria-label": `${f.label}, ${f.width} by ${f.height}${r ? ", open result" : ""}` },
      h("span", { class: "card-stage" }, stage),
      h("span", { class: "card-body" },
        h("span", { class: "card-title" }, h("strong", { title: f.label }, f.label), h("span", {}, `${f.width} × ${f.height}`)),
        h("span", { class: "card-stats" }, stats)));
    if (r) {
      card.addEventListener("click", () => {
        selectFormat(f.key);
        showResult(r, f.label);
        showView("result");
        window.scrollTo({ top: 0 }); // Open the result at its title, not at the grid's scroll offset.
      });
    }
    return card;
  }

  // ------------------------------------------------------------------ events

  function refit() {
    if (el.result.hidden) return;
    fitFrame($("source-stage"), $("source-frame"));
    fitFrame($("output-stage"), $("output-frame"));
  }

  function bindEvents() {
    el.sampleSelect.addEventListener("change", () => loadSample(el.sampleSelect.value));
    el.fileInput.addEventListener("change", () => {
      readFile(el.fileInput.files[0]);
      el.fileInput.value = "";
    });
    for (const type of ["dragenter", "dragover"]) {
      el.dropzone.addEventListener(type, (e) => { e.preventDefault(); el.dropzone.classList.add("is-over"); });
    }
    for (const type of ["dragleave", "drop"]) {
      el.dropzone.addEventListener(type, () => el.dropzone.classList.remove("is-over"));
    }
    el.dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      readFile(e.dataTransfer.files[0]);
    });
    // Dropping anywhere else must not navigate away from the app.
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files.length) readFile(e.dataTransfer.files[0]);
    });

    el.formats.addEventListener("change", () => { if (state.task) run(); });
    el.customRadio.addEventListener("change", () => {
      if (targetCanvas().error) el.customW.focus();
      else if (state.task) run();
    });
    for (const input of [el.customW, el.customH]) {
      input.addEventListener("input", () => { el.customRadio.checked = true; });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
    }
    el.pipeline.addEventListener("change", () => { if (state.task && !el.result.hidden) run(); });
    el.runBtn.addEventListener("click", run);
    el.compareBtn.addEventListener("click", compareAll);
    $("compare-cancel").addEventListener("click", stopCompare);
    $("error-close").addEventListener("click", clearError);

    el.tabResult.addEventListener("click", () => showView("result"));
    el.tabCompare.addEventListener("click", () => showView("compare"));
    for (const tab of [el.tabResult, el.tabCompare]) {
      tab.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        const next = tab === el.tabResult ? el.tabCompare : el.tabResult;
        next.focus();
        next.click();
      });
    }

    el.boxesToggle.addEventListener("change", () => setBoxes(el.boxesToggle.checked));
    el.zoomBoxes.addEventListener("change", () => setBoxes(el.zoomBoxes.checked));
    $("source-stage").addEventListener("click", () => openZoom("source"));
    $("output-stage").addEventListener("click", () => openZoom("output"));
    $("zoom-close").addEventListener("click", () => el.zoom.close());
    for (const input of document.querySelectorAll('input[name="zoom-level"]')) input.addEventListener("change", applyZoom);
    window.addEventListener("resize", () => { if (el.zoom.open) applyZoom(); });
    el.zoom.addEventListener("click", (e) => { if (e.target === el.zoom) el.zoom.close(); });

    $("download-json").addEventListener("click", () => {
      if (!state.result) return;
      const out = state.result.output;
      const blob = new Blob([JSON.stringify(out, null, 2) + "\n"], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      download(`${safeName(state.task.task_id || state.taskName)}_${out.canvas.width}x${out.canvas.height}_output.json`, url);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("download-png").addEventListener("click", () => {
      if (!state.result) return;
      const out = state.result.output;
      download(`${safeName(state.task.task_id || state.taskName)}_${out.canvas.width}x${out.canvas.height}_output.png`, state.result.output_png);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !el.zoom.open) { e.preventDefault(); run(); }
    });
    new ResizeObserver(refit).observe($("source-stage"));
    new ResizeObserver(refit).observe($("output-stage"));
  }

  boot();
})();
