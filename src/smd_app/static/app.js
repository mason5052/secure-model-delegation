"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  token: null,
  status: null,
  models: [],
  catalogLoaded: false,
  catalogBusy: false,
  catalogRequest: 0,
  catalogTimer: null,
  modelDetails: null,
  modelDetailsBusy: false,
  modelDetailsRequest: 0,
  selectedVariant: null,
  selectingModel: null,
  conversation: null,
  run: null,
  runEvents: null,
  install: null,
  installEvents: null,
  lastInstallModel: null,
  pausedInstall: null,
  pausingInstall: false,
  draft: null,
  policyDirty: false,
  activeView: "chat",
  starting: false,
  installing: false,
  compileBusy: false,
  online: false,
  providerDirty: new Set(),
  runStarted: null,
  timer: null,
};

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}

function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function notify(message, isError = false) {
  const box = $("global-message");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = !message;
}

function humanize(value) {
  return String(value || "").replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function apiError(status, detail) {
  if (status === 401 || status === 403) return "This local session needs to be refreshed. Reload the page and try again.";
  if (status === 409) return "Another task is still running. Stop it or wait for it to finish, then try again.";
  if (status === 413) return "This request is too large. Shorten the message and try again.";
  if (status === 422 || status === 400) {
    if (typeof detail === "string" && detail.length < 240 && !/(api[_ -]?key|bearer|sk-)[\s:=]+\S+/i.test(detail)) return detail;
    return "Some information is missing or invalid. Check your entries and try again.";
  }
  if (status === 503) return "The local service is not ready. Check Models and try again.";
  return "The task could not be completed. Check your local model or connection settings and try again.";
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { Accept: "application/json" };
  if (method !== "GET") {
    headers["X-SMD-Token"] = state.token || "";
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (_) {
    throw new Error("The local app is not responding. Restart the desktop app and try again.");
  }
  let result = {};
  if (response.status !== 204) {
    try { result = await response.json(); } catch (_) { /* Empty responses do not contain displayable details. */ }
  }
  if (!response.ok) {
    const detail = result.detail || result.message;
    if ((path.startsWith("/models/") || path.startsWith("/workspace/") || path.startsWith("/voice/") || path.startsWith("/web/")) && typeof detail === "string" && detail.length < 700) throw new Error(detail);
    throw new Error(apiError(response.status, detail));
  }
  return result;
}

function showView(name) {
  if (!$("view-" + name)) return;
  state.activeView = name;
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === `view-${name}`;
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  notify("");
  if (name === "activity") loadActivity();
  if (name === "models") refreshModels();
  $("main-content").focus({ preventScroll: true });
}

function setOnline(online) {
  state.online = online;
  $("server-state-text").textContent = online ? "On this computer" : "Not connected";
  $("server-state").querySelector(".status-dot").classList.toggle("ready", online);
  $("server-state").querySelector(".status-dot").classList.toggle("error", !online);
}

function isReady() { return Boolean(state.status && state.status.runtime && state.status.runtime.ready); }
function hasActiveRun() { return Boolean(state.run || state.starting); }
function hasPolicyRules(draft) { return Boolean(draft && (Array.isArray(draft.rules) ? draft.rules.length : draft.rules && Object.keys(draft.rules).length)); }
function canActivateDraft(draft) { return Boolean(draft && draft.id && !draft.active && hasPolicyRules(draft) && Array.isArray(draft.issues) && draft.issues.length === 0); }

function updateControls() {
  const ready = isReady();
  const running = hasActiveRun();
  const busy = running || state.installing || Boolean(state.selectingModel);
  $("submit-prompt").disabled = !state.online || !ready || busy || !$("prompt-input").value.trim() || Boolean(state.status && state.status.busy);
  $("submit-prompt").hidden = running;
  $("stop-run").hidden = !running;
  $("stop-run").disabled = !state.run;
  $("prompt-input").disabled = running;
  $("destination").disabled = running;
  $("new-chat").disabled = running;
  $("unload-model").disabled = !ready || busy || Boolean(state.status && state.status.busy);
  $("compile-policy").disabled = !ready || busy || state.compileBusy || !$("policy-text").value.trim();
  $("policy-text").disabled = state.compileBusy;
  $("activate-policy").disabled = busy || state.compileBusy || !canActivateDraft(state.draft);
  $("chat-setup").hidden = ready;
  $("chat-ready-hint").hidden = !ready;
  if (running) $("composer-help").textContent = "Your request is in progress. Stop cancels the current task; an external request may already have been sent.";
  else if (state.installing) $("composer-help").textContent = "A model is downloading. Choose Use in Models when the download is complete.";
  else if (state.selectingModel) $("composer-help").textContent = "Checking your selected model with the local runtime.";
  else if (!ready) $("composer-help").textContent = "Choose a local model to begin. External connections are optional.";
  else if ($("destination").value === "local") $("composer-help").textContent = "This destination runs locally. Your active policy still determines how the request is handled.";
  else $("composer-help").textContent = "The app follows your policy before calling this provider. Some requests may stay local or be declined.";
  renderInstalledModels();
  updateModelButtons();
}

function renderStatus() {
  const current = state.status || {};
  const runtime = current.runtime || {};
  const policy = current.policy || {};
  const ready = Boolean(runtime.ready);
  const modelName = runtime.model || "Local model";
  $("model-dot").classList.toggle("ready", ready);
  $("runtime-dot").classList.toggle("ready", ready || Boolean(runtime.runtime_ready));
  $("runtime-dot").classList.toggle("error", Boolean(runtime.error));
  $("sidebar-model-name").textContent = modelName;
  $("sidebar-model-state").textContent = ready ? "Ready on this computer" : state.installing ? "Preparing model" : "Setup required";
  if (ready) {
    $("runtime-title").textContent = `${modelName} is ready`;
    $("runtime-description").textContent = "Local inference is available. Your model can interpret policies and answer requests.";
  } else if (runtime.runtime_ready) {
    $("runtime-title").textContent = "Local runtime available";
    $("runtime-description").textContent = "No model is active. Download a model, then choose Use from the installed list.";
  } else {
    $("runtime-title").textContent = "Choose a model to get started";
    $("runtime-description").textContent = "Browse the catalog and download a file. The app will prepare the local runtime.";
  }
  if (runtime.error && !state.installing) $("runtime-description").textContent = "The local runtime needs attention. Try selecting a model again or check its setup status.";
  $("active-policy-preview").textContent = policy.text || "No active policy. Open Policy to create and activate your rules.";
  if (!state.policyDirty && !state.compileBusy) {
    if (current.draft && current.draft.text) {
      $("policy-text").value = current.draft.text;
      if (JSON.stringify(state.draft) !== JSON.stringify(current.draft)) renderPolicyDraft(current.draft);
      state.draft = current.draft;
      $("policy-state").textContent = "SAVED DRAFT";
    } else {
      $("policy-text").value = policy.text || "";
      state.draft = null;
      $("policy-state").textContent = "ACTIVE POLICY";
      $("activate-policy").hidden = true;
    }
  }
  $("save-content").checked = Boolean(current.settings && current.settings.save_content);
  $("save-content-label").textContent = $("save-content").checked ? "On" : "Off";
  const previousDestination = $("destination").value;
  $("destination").replaceChildren();
  const local = element("option", null, "Local model");
  local.value = "local";
  $("destination").append(local);
  const providers = Array.isArray(current.providers) ? current.providers : Object.entries(current.providers || {}).map(([id, item]) => ({ id, ...item }));
  for (const id of ["openai", "anthropic", "remote"]) {
    const provider = providers.find((item) => item.id === id) || {};
    const configured = Boolean(provider.configured);
    $(id + "-status").textContent = configured ? "CONNECTED" : "NOT CONNECTED";
    $(id + "-key-state").textContent = configured ? `Key held in memory${provider.masked_key ? `: ${provider.masked_key}` : "."}` : "No key configured.";
    if (!state.providerDirty.has(id) && document.activeElement !== $(id + "-model") && provider.model) $(id + "-model").value = provider.model;
    document.querySelector(`.provider-disconnect[data-provider="${id}"]`).disabled = !configured;
    if (configured) {
      const option = element("option", null, id === "openai" ? "OpenAI" : id === "remote" ? "Your remote server" : "Anthropic");
      option.value = id;
      $("destination").append(option);
    }
  }
  if ([...$("destination").options].some((option) => option.value === previousDestination)) $("destination").value = previousDestination;
  updateControls();
}

async function refreshStatus(quiet = false) {
  try {
    state.status = await api("/status");
    setOnline(true);
    renderStatus();
  } catch (error) {
    setOnline(false);
    updateControls();
    if (!quiet) notify(error.message, true);
  }
}

async function refreshModels() {
  await refreshStatus(true);
  await searchCatalog();
}

function compactNumber(number) {
  const value = Number(number);
  if (!Number.isFinite(value)) return "Not reported";
  return new Intl.NumberFormat([], { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function modelUpdated(value) {
  if (!value) return "Date not reported";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date not reported" : date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function licenseLabel(license) {
  if (Array.isArray(license)) return license.join(", ") || "Not reported";
  return license || "Not reported";
}

async function searchCatalog() {
  clearTimeout(state.catalogTimer);
  const request = ++state.catalogRequest;
  state.catalogBusy = true;
  $("search-models").disabled = true;
  $("search-models").textContent = "Searching...";
  $("catalog-summary").textContent = `Searching Hugging Face for ${$("model-format").value.toUpperCase()} model repositories...`;
  $("model-catalog").setAttribute("aria-busy", "true");
  const query = new URLSearchParams({ query: $("model-search").value.trim(), sort: $("model-sort").value, format: $("model-format").value });
  try {
    const catalog = await api(`/models/catalog?${query.toString()}`);
    if (request !== state.catalogRequest) return;
    state.models = Array.isArray(catalog.models) ? catalog.models : [];
    state.catalogLoaded = true;
    $("catalog-summary").textContent = `${state.models.length} ${state.models.length === 1 ? "repository" : "repositories"} / ${$("model-sort").value === "downloads" ? "Most downloaded" : "Recently updated"}`;
    $("catalog-source").textContent = `SOURCE: ${String(catalog.source || "Hugging Face").toUpperCase()}`;
    renderHubCatalog();
  } catch (error) {
    if (request !== state.catalogRequest) return;
    state.models = [];
    $("catalog-summary").textContent = "The online catalog is unavailable.";
    const empty = element("div", "catalog-empty catalog-error");
    empty.append(icon("info"), element("h3", null, "The catalog could not be loaded."), element("p", null, error.message), element("p", "field-help", "Your installed models remain available below. Try another search or refresh when your connection is available."));
    $("model-catalog").replaceChildren(empty);
  } finally {
    if (request === state.catalogRequest) {
      state.catalogBusy = false;
      $("search-models").disabled = false;
      $("search-models").textContent = "Search";
      $("model-catalog").removeAttribute("aria-busy");
    }
  }
}

function renderHubCatalog() {
  const catalog = $("model-catalog");
  catalog.replaceChildren();
  if (!state.models.length) {
    const empty = element("div", "catalog-empty");
    empty.append(element("h3", null, "No matching repositories."), element("p", null, "Try a different model family, author, or a shorter search. There is no built-in model list."));
    catalog.append(empty);
    return;
  }
  state.models.forEach((model) => {
    const selected = Boolean(state.modelDetails && state.modelDetails.id === model.id);
    const card = element("button", `hub-model${selected ? " selected" : ""}`);
    card.type = "button";
    card.setAttribute("aria-pressed", selected ? "true" : "false");
    const top = element("span", "hub-model-heading");
    top.append(icon("model"), element("strong", null, model.name || String(model.id).split("/").slice(1).join("/") || model.id), element("span", "hub-model-chevron", ">"));
    const author = element("span", "hub-model-author", model.author || String(model.id).split("/")[0]);
    const metadata = element("span", "hub-model-metadata");
    metadata.append(element("span", null, `${compactNumber(model.downloads)} downloads`), element("span", null, `Updated ${modelUpdated(model.last_modified)}`));
    const tags = element("span", "hub-model-tags");
    tags.append(element("span", "catalog-tag", model.format || "GGUF"), element("span", "catalog-tag", licenseLabel(model.license)), element("span", "catalog-tag compatibility-tag", "Compatibility not checked"));
    if (model.gated) tags.append(element("span", "catalog-tag gated-tag", "Access restricted"));
    card.append(top, author, metadata, tags);
    card.addEventListener("click", () => loadModelDetails(model.id));
    catalog.append(card);
  });
}

async function loadModelDetails(repo) {
  const request = ++state.modelDetailsRequest;
  state.modelDetailsBusy = true;
  state.modelDetails = { id: repo };
  state.selectedVariant = null;
  renderHubCatalog();
  const panel = $("model-detail");
  const loading = element("div", "model-detail-empty");
  loading.append(icon("model", "icon large-icon"), element("h3", null, "Reading repository files..."), element("p", null, "Checking available model files and repository metadata."));
  panel.replaceChildren(loading);
  panel.setAttribute("aria-busy", "true");
  try {
    const details = await api(`/models/details?${new URLSearchParams({ repo, format: $("model-format").value }).toString()}`);
    if (request !== state.modelDetailsRequest) return;
    state.modelDetails = details;
    state.selectedVariant = null;
    renderModelDetails();
  } catch (error) {
    if (request !== state.modelDetailsRequest) return;
    const empty = element("div", "model-detail-empty catalog-error");
    empty.append(icon("info", "icon large-icon"), element("h3", null, "Files could not be loaded."), element("p", null, error.message), element("p", "field-help", "Select the repository again to retry. No model has been downloaded or activated."));
    panel.replaceChildren(empty);
  } finally {
    if (request === state.modelDetailsRequest) {
      state.modelDetailsBusy = false;
      panel.removeAttribute("aria-busy");
    }
  }
}

function renderModelDetails() {
  const details = state.modelDetails;
  if (!details) return;
  const panel = $("model-detail");
  panel.replaceChildren();
  const heading = element("div", "model-detail-heading");
  heading.append(element("span", "small-label", "REPOSITORY FILES"), element("h2", null, details.id));
  const repositoryLink = element("a", "repository-link", "View on Hugging Face");
  repositoryLink.href = `https://huggingface.co/${String(details.id).split("/").map(encodeURIComponent).join("/")}`;
  repositoryLink.target = "_blank";
  repositoryLink.rel = "noopener noreferrer";
  heading.append(repositoryLink);
  panel.append(heading);
  const metadata = element("dl", "repository-metadata");
  for (const [label, value] of [["License", licenseLabel(details.license)], ["Revision", details.revision ? String(details.revision).slice(0, 12) : "Not reported"], ["Access", details.gated ? "Restricted / authentication may be required" : "Public listing"]]) {
    metadata.append(element("dt", null, label), element("dd", null, value));
  }
  panel.append(metadata);
  if (details.gated) panel.append(element("p", "policy-issue", "This repository has access restrictions. Only files that the app can download without additional authorization are available here."));
  const header = element("div", "variant-heading");
  header.append(element("h3", null, details.format === "MLX" ? "Download the repository" : "Choose a file"), element("span", "mono muted", details.format === "MLX" ? "MLX WEIGHTS" : "GGUF VARIANTS"));
  panel.append(header, element("p", "variant-help", "Quantization changes model size and precision. Review the actual file size, license, and model requirements before downloading."));
  const variants = Array.isArray(details.variants) ? details.variants : [];
  const list = element("div", "variant-list");
  if (!variants.length) list.append(element("p", "field-help", "No installable files were listed in this repository. Try another model or format."));
  variants.forEach((variant, index) => {
    const row = element("label", `variant-row${variant.installable && variant.model_ref ? "" : " unavailable"}`);
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "model-variant";
    radio.value = String(index);
    radio.disabled = !variant.installable || !variant.model_ref;
    radio.checked = state.selectedVariant === variant;
    radio.addEventListener("change", () => {
      state.selectedVariant = variant;
      list.querySelectorAll(".variant-row").forEach((item) => item.classList.toggle("chosen", Boolean(item.querySelector("input").checked)));
      updateModelButtons();
    });
    const copy = element("span", "variant-copy");
    copy.append(element("strong", null, variant.filename || variant.id));
    const facts = element("span", "variant-facts");
    facts.append(element("span", "catalog-tag", variant.quantization || "Variant not specified"));
    const size = Number(variant.size_bytes) > 0 ? `${(Number(variant.size_bytes) / 1000000000).toLocaleString([], { maximumFractionDigits: 2 })} GB` : Number(variant.size_gb) > 0 ? `${variant.size_gb} GB` : "Size not reported";
    facts.append(element("span", null, size));
    copy.append(facts);
    const memory = state.hardware?.total_memory_bytes;
    if (memory && Number(variant.size_bytes) > 0) {
      const weight = Number(variant.size_bytes);
      copy.append(element("small", "variant-device-fit", weight > memory
        ? "Weights exceed this Mac's physical memory. Choose a smaller variant or verify runtime offloading support."
        : `Weights are below this Mac's ${(memory / 1024 ** 3).toFixed(0)} GB memory. Runtime and context overhead still require a local compatibility check.`));
    }
    if (!variant.installable || !variant.model_ref) copy.append(element("small", "variant-unavailable", variant.reason || "This file cannot be installed by the current runtime."));
    row.append(radio, copy);
    list.append(row);
  });
  panel.append(list);
  const footer = element("div", "variant-download-footer");
  const button = element("button", "button primary", "Download selected file");
  button.id = "download-variant";
  button.type = "button";
  button.prepend(icon("download"));
  button.addEventListener("click", () => {
    if (state.selectedVariant && state.selectedVariant.model_ref) installModel(state.selectedVariant.model_ref);
  });
  footer.append(button, element("p", "field-help", "Downloading adds the model to your local library. Choose Use separately to check and activate it."));
  panel.append(footer);
  updateModelButtons();
}

function updateModelButtons() {
  const busy = state.installing || hasActiveRun() || Boolean(state.selectingModel);
  const download = $("download-variant");
  if (download) download.disabled = busy || !state.selectedVariant || !state.selectedVariant.installable || !state.selectedVariant.model_ref;
  $("advanced-model-download").disabled = busy;
  $("advanced-model-tag").disabled = busy;
}

function renderInstalledModels() {
  const runtime = state.status && state.status.runtime || {};
  const models = Array.isArray(runtime.installed_models) ? runtime.installed_models : [];
  const panel = $("installed-models");
  panel.replaceChildren();
  $("installed-count").textContent = `${models.length} ${models.length === 1 ? "model" : "models"}`;
  if (!models.length) {
    const empty = element("div", "installed-empty");
    const copy = element("div");
    copy.append(element("strong", null, "No downloaded models yet."), element("p", null, "Download a file above, then choose Use to activate it."));
    empty.append(icon("local"), copy);
    panel.append(empty);
    return;
  }
  models.forEach((model) => {
    const active = runtime.model === model && Boolean(runtime.ready);
    const checking = state.selectingModel === model;
    const row = element("div", `installed-row${active ? " selected" : ""}`);
    const info = element("div", "installed-copy");
    const title = element("div", "installed-title");
    title.append(icon("model"), element("strong", null, model));
    if (active) title.append(element("span", "tiny-tag", "ACTIVE"));
    info.append(title, element("small", null, active ? "Selected and locally checked" : checking ? "Checking compatibility with the local runtime..." : "Downloaded / choose Use to check and activate"));
    const actions = element("div", "installed-actions");
    const use = element("button", `button ${active ? "secondary" : "primary"} small-button`, checking ? "Checking..." : active ? "In use" : "Use");
    use.type = "button";
    use.disabled = active || state.installing || hasActiveRun() || Boolean(state.selectingModel);
    use.addEventListener("click", () => selectModel(model));
    const remove = element("button", "button secondary small-button", "Remove");
    remove.type = "button";
    remove.disabled = state.installing || hasActiveRun() || Boolean(state.selectingModel);
    remove.addEventListener("click", () => deleteModel(model));
    actions.append(use, remove);
    row.append(info, actions);
    panel.append(row);
  });
}

async function selectModel(model) {
  if (!model || state.installing || hasActiveRun() || state.selectingModel) return;
  state.selectingModel = model;
  notify("Checking the selected model with your local runtime. Your active model changes only if the check succeeds.");
  updateControls();
  try {
    await api("/models/select", { method: "POST", body: { model } });
    await refreshStatus(true);
    notify("The selected model passed the local check and is now active. You can return to Chat.");
  } catch (error) { notify(error.message, true); }
  finally {
    state.selectingModel = null;
    await refreshStatus(true);
    updateControls();
  }
}

function stream(path, onEvent, onDisconnect) {
  const source = new EventSource(`/api/v1${path}`, { withCredentials: true });
  let ended = false;
  let disconnectTimer = null;
  function receive(event) {
    if (ended) return;
    clearTimeout(disconnectTimer);
    disconnectTimer = null;
    let item;
    try { item = JSON.parse(event.data); } catch (_) { return; }
    if (!item.type && event.type !== "message") item.type = event.type;
    if (["completed", "failed", "cancelled"].includes(item.type)) {
      ended = true;
      source.close();
    }
    onEvent(item);
  }
  source.onmessage = receive;
  ["progress", "completed", "failed", "cancelled"].forEach((type) => source.addEventListener(type, receive));
  source.onopen = () => { clearTimeout(disconnectTimer); disconnectTimer = null; };
  source.onerror = () => {
    if (ended || disconnectTimer) return;
    disconnectTimer = setTimeout(() => {
      if (ended) return;
      ended = true;
      source.close();
      onDisconnect();
    }, 18000);
  };
  return { close() { ended = true; clearTimeout(disconnectTimer); source.close(); } };
}

async function installModel(model) {
  if (!model || state.installing || hasActiveRun() || state.selectingModel) return;
  notify("");
  state.lastInstallModel = model;
  state.pausedInstall = null;
  $("pause-install").hidden = false;
  $("resume-install").hidden = true;
  state.installing = true;
  $("model-install-progress").hidden = false;
  $("install-title").textContent = `Downloading ${model}`;
  $("install-message").textContent = "Checking the local runtime.";
  $("install-percent").textContent = "";
  $("install-progress-bar").style.width = "";
  $("install-progress-bar").classList.add("indeterminate");
  $("retry-install").hidden = true;
  $("cancel-install").hidden = false;
  $("cancel-install").disabled = true;
  updateControls();
  try {
    const job = await api("/models/install", { method: "POST", body: { model } });
    state.install = job.id;
    $("cancel-install").disabled = false;
    state.installEvents = stream(`/jobs/${encodeURIComponent(job.id)}/events`, handleInstallEvent, () => finishInstall(false, "The setup connection was interrupted. Refresh to check the model, or try again."));
  } catch (error) { finishInstall(false, error.message); }
}

function handleInstallEvent(event) {
  if (state.pausingInstall) return;
  if (event.type === "progress") {
    $("install-title").textContent = event.stage ? humanize(event.stage) : `Preparing ${state.lastInstallModel}`;
    $("install-message").textContent = event.message || "Your local model is being prepared.";
    const completed = Number(event.completed || event.downloaded || 0);
    const total = Number(event.total || 0);
    let percentage = event.percent ?? event.percentage ?? (total > 0 ? completed / total * 100 : null);
    if (percentage !== null && Number.isFinite(Number(percentage))) {
      percentage = Math.max(0, Math.min(100, Number(percentage)));
      $("install-progress-bar").classList.remove("indeterminate");
      $("install-progress-bar").style.width = `${percentage}%`;
      $("install-percent").textContent = `${Math.round(percentage)}%`;
    }
  } else if (event.type === "completed") finishInstall(true, "Download complete. Choose Use from the installed list to check and activate this model.");
  else if (event.type === "cancelled") finishInstall(false, "Setup was cancelled. You can retry when you are ready.");
  else if (event.type === "failed") finishInstall(false, typeof event.error === "string" ? event.error : "Setup could not finish. Check your network, disk space, and local runtime, then try again.");
}

async function finishInstall(success, message) {
  if (state.installEvents) state.installEvents.close();
  state.installEvents = null;
  state.install = null;
  state.installing = false;
  $("install-title").textContent = success ? "Model downloaded" : "Download needs attention";
  $("install-message").textContent = message;
  $("install-progress-bar").classList.remove("indeterminate");
  $("install-progress-bar").style.width = success ? "100%" : "0%";
  $("install-percent").textContent = success ? "100%" : "";
  $("cancel-install").hidden = true;
  $("pause-install").hidden = true;
  $("resume-install").hidden = true;
  $("retry-install").hidden = success;
  await refreshStatus(true);
  updateControls();
  if (success) notify("Download complete. Choose Use in the installed list to check and activate the model. Your current selection has not changed.");
}

async function pauseInstall() {
  if (!state.install || state.pausingInstall) return;
  state.pausingInstall = true;
  const id = state.install;
  $("pause-install").disabled = true;
  try {
    await api(`/jobs/${encodeURIComponent(id)}/pause`, { method: "POST" });
    if (state.installEvents) state.installEvents.close();
    state.installEvents = null; state.pausedInstall = id; state.install = null; state.installing = false;
    $("install-title").textContent = "Download paused";
    $("install-message").textContent = "Downloaded parts stay on this computer. Resume continues the selected model download.";
    $("pause-install").hidden = true; $("resume-install").hidden = false;
    $("cancel-install").disabled = false;
    updateControls();
  } catch (error) { notify(error.message, true); }
  finally { state.pausingInstall = false; $("pause-install").disabled = false; }
}

async function resumeInstall() {
  if (!state.pausedInstall || state.installing) return;
  $("resume-install").disabled = true;
  try {
    const job = await api(`/jobs/${encodeURIComponent(state.pausedInstall)}/resume`, { method: "POST" });
    state.install = job.id || job.job_id; state.pausedInstall = null; state.installing = true;
    $("resume-install").hidden = true; $("pause-install").hidden = false; $("cancel-install").hidden = false;
    $("install-message").textContent = "Resuming the selected download...";
    state.installEvents = stream(`/jobs/${encodeURIComponent(state.install)}/events`, handleInstallEvent, () => finishInstall(false, "The download connection stopped. Check model status before retrying."));
    updateControls();
  } catch (error) { notify(error.message, true); }
  finally { $("resume-install").disabled = false; }
}

async function cancelInstall() {
  if (state.pausedInstall) { state.pausedInstall = null; await finishInstall(false, "Paused download cancelled. Retained parts may be reused if you download this model again."); return; }
  if (!state.install) return;
  $("cancel-install").disabled = true;
  try {
    await api(`/jobs/${encodeURIComponent(state.install)}/cancel`, { method: "POST" });
    $("install-message").textContent = "Cancelling setup. Waiting for the local task to stop.";
  } catch (error) { notify(error.message, true); $("cancel-install").disabled = false; }
}

async function deleteModel(model) {
  if (!window.confirm(`Remove ${model} from this computer? You can download it again later.`)) return;
  try {
    await api(`/models/${encodeURIComponent(model)}`, { method: "DELETE" });
    await refreshStatus(true);
    notify("The local model was removed.");
  } catch (error) { notify(error.message, true); }
}

function renderClauses(container, rules) {
  const items = Array.isArray(rules) ? rules : Object.entries(rules || {}).map(([id, rule]) => typeof rule === "object" && rule !== null ? { id, ...rule } : { id, text: String(rule) });
  if (!items.length) {
    container.append(element("p", "muted", "No clauses were returned. Revise the draft before activation."));
    return;
  }
  items.forEach((rule, index) => {
    const row = element("div", "clause-item");
    if (typeof rule === "string") {
      row.append(element("strong", null, `CLAUSE ${index + 1}`), element("p", null, rule));
    } else {
      row.append(element("strong", null, rule.id || `CLAUSE ${index + 1}`));
      if (rule.text || rule.description || rule.summary || rule.source_text) row.append(element("p", null, rule.text || rule.description || rule.summary || rule.source_text));
      else {
        const parts = [];
        for (const [key, value] of Object.entries(rule)) {
          if (["id", "priority"].includes(key) || value === null || value === undefined) continue;
          const formatted = Array.isArray(value) ? value.join(", ") : typeof value === "object" ? Object.entries(value).map(([k, v]) => `${humanize(k)}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join("; ") : String(value);
          parts.push(`${humanize(key)}: ${formatted}`);
        }
        row.append(element("p", null, parts.join(". ")));
      }
      if (rule.action) {
        const actions = { allow: "Allow", redact: "Remove matching information before external use", local_only: "Keep processing local", deny: "Block this request", clarify: "Ask for clarification" };
        const targets = { local: "Local model", openai: "OpenAI", anthropic: "Anthropic", remote: "Your remote server" };
        row.append(element("p", "field-help", `Handling: ${actions[rule.action] || humanize(rule.action)}`));
        row.append(element("p", "field-help", `Information: ${(rule.info || []).map(humanize).join(", ") || "Not specified"}`));
        row.append(element("p", "field-help", `Applies to: ${(rule.targets || []).map((target) => targets[target] || target).join(", ") || "Not specified"}`));
      }
    }
    container.append(row);
  });
}

function renderPolicyDraft(draft) {
  state.draft = draft;
  const panel = $("policy-interpretation");
  panel.replaceChildren();
  if (draft.interpretation || draft.summary) panel.append(element("p", "field-help", draft.interpretation || draft.summary));
  const issues = Array.isArray(draft.issues) ? draft.issues : [];
  issues.forEach((issue) => panel.append(element("div", "policy-issue", typeof issue === "string" ? issue : issue.message || issue.description || "Review this clause for ambiguity.")));
  renderClauses(panel, draft.rules);
  $("interpretation-state").textContent = issues.length ? "REVIEW ISSUES" : hasPolicyRules(draft) ? "READY FOR YOUR REVIEW" : "INTERPRETATION REQUIRED";
  $("activate-policy").hidden = !canActivateDraft(draft);
}

async function compilePolicy(event) {
  event.preventDefault();
  const text = $("policy-text").value.trim();
  if (!text || !isReady() || state.compileBusy) return;
  state.compileBusy = true;
  state.draft = null;
  $("compile-policy").textContent = "Interpreting locally...";
  $("activate-policy").hidden = true;
  $("policy-state").textContent = "DRAFT";
  $("interpretation-state").textContent = "LOCAL MODEL WORKING";
  notify("");
  updateControls();
  try {
    const draft = await api("/policies/compile", { method: "POST", body: { text } });
    state.policyDirty = false;
    renderPolicyDraft(draft);
    notify("Review every clause. The interpretation may miss or misunderstand a rule; your existing policy is still active.");
  } catch (error) {
    $("interpretation-state").textContent = "INTERPRETATION FAILED";
    notify(error.message, true);
  } finally {
    state.compileBusy = false;
    $("compile-policy").textContent = "Review interpretation";
    $("compile-policy").append(icon("arrow"));
    updateControls();
  }
}

async function activatePolicy() {
  if (!canActivateDraft(state.draft)) return;
  $("activate-policy").disabled = true;
  try {
    await api(`/policies/${encodeURIComponent(state.draft.id)}/activate`, { method: "POST" });
    state.draft = null;
    state.policyDirty = false;
    $("activate-policy").hidden = true;
    $("policy-state").textContent = "ACTIVE POLICY";
    $("interpretation-state").textContent = "ACTIVE";
    await refreshStatus(true);
    notify("Your reviewed policy is now active for new requests.");
  } catch (error) { notify(error.message, true); updateControls(); }
}

function addMessage(role, text, footnote) {
  $("chat-empty").hidden = true;
  const message = element("article", `chat-message ${role}`);
  message.append(element("div", "message-heading", role === "user" ? "You" : role === "error" ? "Task stopped" : "Assistant"));
  message.append(element("div", "message-body", text));
  if (footnote) message.append(element("div", "message-footnote", footnote));
  $("chat-transcript").append(message);
  $("chat-transcript").scrollTop = $("chat-transcript").scrollHeight;
  return message;
}

function startRunTimer() {
  state.runStarted = Date.now();
  clearInterval(state.timer);
  const tick = () => {
    const seconds = Math.floor((Date.now() - state.runStarted) / 1000);
    $("run-elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  };
  tick();
  state.timer = setInterval(tick, 1000);
}

async function submitPrompt(event) {
  event.preventDefault();
  const prompt = $("prompt-input").value.trim();
  if (!prompt || !isReady() || hasActiveRun() || state.installing) return;
  state.starting = true;
  notify("");
  updateControls();
  $("run-progress").hidden = false;
  $("run-stage").textContent = "Starting your request";
  $("run-message").textContent = "Preparing your policy and conversation context.";
  startRunTimer();
  const destination = $("destination").value;
  addMessage("user", prompt);
  $("prompt-input").value = "";
  try {
    if (!state.conversation) {
      const conversation = await api("/conversations", { method: "POST" });
      state.conversation = conversation.id;
      $("conversation-label").textContent = "Current conversation";
    }
    const run = await api("/runs", { method: "POST", body: { conversation_id: state.conversation, prompt, destination } });
    state.run = run.id;
    state.starting = false;
    updateControls();
    state.runEvents = stream(`/runs/${encodeURIComponent(run.id)}/events`, handleRunEvent, () => {
      addMessage("error", "The progress connection was interrupted. Check Activity before sending again; an external request may already have been made.");
      finishRun();
    });
  } catch (error) {
    addMessage("error", error.message);
    finishRun();
  }
}

function handleRunEvent(event) {
  if (event.type === "progress") {
    $("run-stage").textContent = humanize(event.stage || "Working");
    $("run-message").textContent = event.message || "Your request is being processed.";
    $("footer-status").textContent = humanize(event.stage || "Working").toUpperCase();
  } else if (event.type === "completed") {
    const result = event.result || event;
    const route = routeLabel(result.route);
    addMessage("assistant", result.answer || "This request finished without an answer body. Open the details to inspect the selected route.", `${route}. ${result.external_attempted ? "An external request was attempted." : "No external request was attempted."}`);
    renderRunDetails(result);
    finishRun();
  } else if (event.type === "cancelled") {
    addMessage("error", "The task was cancelled. Cancellation does not retract a request already sent to an external provider.");
    finishRun();
  } else if (event.type === "failed") {
    const cancelled = event.cancelled || event.code === "cancelled" || event.stage === "cancelled";
    addMessage("error", cancelled ? "The task was cancelled. An external request may already have been sent." : typeof event.error === "string" ? event.error : "This task could not finish. Check the local model or provider connection and try again. Activity may contain the last recorded stage.");
    finishRun();
  }
}

function routeLabel(route) {
  const names = {
    local_process: "Handled locally",
    local_summary: "Local summary selected",
    deny_request: "Request declined",
    ask_clarification: "Clarification requested",
    delegate_sanitized_to_external_ai: "Transformed external delegation",
    delegate_pseudocode_to_external_ai: "Code-replaced external delegation",
    local: "Handled locally",
    deny: "Request declined",
    clarify: "Clarification requested",
  };
  return names[route] || humanize(route || "Route not recorded");
}

function addDetail(container, label, value) {
  container.append(element("div", "detail-label", label));
  container.append(element("div", "detail-value", value));
}

function renderRunDetails(result) {
  const panel = $("run-details-content");
  panel.replaceChildren();
  addDetail(panel, "Chosen path", routeLabel(result.route));
  addDetail(panel, "External execution", result.external_attempted ? "An external request was attempted." : "No external request was attempted.");
  if (result.rule_ids && result.rule_ids.length) addDetail(panel, "Policy clauses", result.rule_ids.join(", "));
  if (result.reasons && result.reasons.length) {
    panel.append(element("div", "detail-label", "Decision reasons"));
    const list = element("ul", "detail-list");
    result.reasons.forEach((reason) => list.append(element("li", null, reason)));
    panel.append(list);
  }
  if (result.transforms) {
    const transforms = Array.isArray(result.transforms) ? result.transforms : [result.transforms];
    if (transforms.length) addDetail(panel, "Transformations", transforms.map((item) => typeof item === "string" ? item : item.description || (item.kind ? `${humanize(item.kind)}${item.count !== undefined ? ` (${item.count})` : ""}` : item.type || item.action || "Transformation recorded")).join("; "));
  }
  panel.append(element("div", "detail-label", result.external_attempted ? "Outgoing payload" : "Prepared payload"));
  panel.append(element("pre", "detail-payload", (typeof result.payload === "object" ? JSON.stringify(result.payload, null, 2) : result.payload) || "No external payload recorded."));
  panel.append(element("div", "detail-label", "Limited content inspection"));
  const inspection = result.inspection;
  let explanation = "The app checks recognized information patterns. This is not a semantic privacy review or proof of confidentiality.";
  if (typeof inspection === "string") explanation = `${inspection} ${explanation}`;
  else if (inspection) {
    if (inspection.message || inspection.summary) explanation = `${inspection.message || inspection.summary} ${explanation}`;
    else if (inspection.status) explanation = `Recorded status: ${humanize(inspection.status)}. ${explanation}`;
    else if (inspection.finding_count !== undefined) explanation = `${inspection.finding_count} recognized-pattern finding${inspection.finding_count === 1 ? "" : "s"}${inspection.uncertain ? "; some content remains uncertain" : ""}. ${explanation}`;
    if (Array.isArray(inspection.labels) && inspection.labels.length) addDetail(panel, "Recognized categories", inspection.labels.map(humanize).join(", "));
    if (inspection.local_feasibility) addDetail(panel, "Local processing note", typeof inspection.local_feasibility === "string" ? inspection.local_feasibility : inspection.local_feasibility.reason || inspection.local_feasibility.message || humanize(inspection.local_feasibility.status || "Recorded"));
  }
  panel.append(element("p", "fine-print", explanation));
}

async function finishRun() {
  if (state.runEvents) state.runEvents.close();
  state.runEvents = null;
  state.run = null;
  state.starting = false;
  clearInterval(state.timer);
  $("run-progress").hidden = true;
  $("stop-run").textContent = "Stop";
  $("footer-status").textContent = "YOUR POLICY. YOUR DESTINATION.";
  await refreshStatus(true);
  updateControls();
  $("prompt-input").focus({ preventScroll: true });
}

async function cancelRun() {
  if (!state.run) return;
  $("stop-run").disabled = true;
  $("stop-run").textContent = "Stopping...";
  try {
    await api(`/runs/${encodeURIComponent(state.run)}/cancel`, { method: "POST" });
    $("run-message").textContent = "Cancellation requested. Waiting for the current task to stop.";
  } catch (error) {
    notify(error.message, true);
    $("stop-run").disabled = false;
    $("stop-run").textContent = "Stop";
  }
}

async function newConversation() {
  if (hasActiveRun()) return;
  try {
    const conversation = await api("/conversations", { method: "POST" });
    state.conversation = conversation.id;
    $("chat-transcript").querySelectorAll(".chat-message").forEach((message) => message.remove());
    $("chat-empty").hidden = false;
    $("conversation-label").textContent = "New conversation";
    $("prompt-input").value = "";
    $("run-details-content").replaceChildren(element("p", "muted", "Details appear after your first request."));
    $("run-details").open = false;
    updateControls();
    $("prompt-input").focus({ preventScroll: true });
  } catch (error) { notify(error.message, true); }
}

async function configureProvider(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.dataset.provider;
  const button = form.querySelector('button[type="submit"]');
  const apiKey = $(id + "-key").value.trim();
  const model = $(id + "-model").value.trim();
  const privateEntry = Boolean(window.smdDesktop?.configureProvider);
  if (!model || (!privateEntry && !apiKey)) return;
  button.disabled = true;
  try {
    if (privateEntry) {
      const result = await window.smdDesktop.configureProvider({ provider: id, model, ...(id === "remote" ? { base_url: $("remote-base-url").value.trim() } : {}) });
      if (result.canceled) return;
    } else {
      await api(`/providers/${id}`, { method: "PUT", body: { api_key: apiKey, model, ...(id === "remote" ? { base_url: $("remote-base-url").value.trim() } : {}) } });
    }
    state.providerDirty.delete(id);
    $(id + "-key").value = "";
    await refreshStatus(true);
    notify(`${id === "openai" ? "OpenAI" : id === "remote" ? "Your remote server" : "Anthropic"} connection saved in memory. Select it in Chat to try delegation. Configuration alone does not verify a successful provider call.`);
  } catch (error) {
    $(id + "-key").value = "";
    notify(error.message, true);
  } finally { button.disabled = false; }
}

async function disconnectProvider(id) {
  try {
    await api(`/providers/${id}`, { method: "DELETE" });
    $(id + "-key").value = "";
    await refreshStatus(true);
    notify("The provider key was removed from this app's memory.");
  } catch (error) { notify(error.message, true); }
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function loadActivity() {
  window.dispatchEvent(new CustomEvent("smd:activity"));
  try {
    const activity = await api("/activity");
    const runs = activity.runs || [];
    $("activity-count").textContent = `${runs.length} ${runs.length === 1 ? "record" : "records"}`;
    const list = $("activity-list");
    list.replaceChildren();
    if (!runs.length) {
      const empty = element("div", "activity-empty");
      empty.append(element("h3", null, "A clean desk."), element("p", null, "Your request records will appear here after you start a conversation."));
      list.append(empty);
    }
    runs.forEach((run) => {
      const row = element("div", "activity-row");
      const time = element("div");
      time.append(element("strong", null, formatDate(run.created_at)), element("small", "mono", run.id ? String(run.id).slice(0, 12) : ""));
      const route = element("div");
      route.append(element("strong", null, routeLabel(run.route)), element("small", null, run.destination === "local" ? "Local model" : humanize(run.destination)));
      const status = element("div");
      status.append(element("strong", null, humanize(run.status || "Recorded")), element("small", null, run.has_content ? "Content saved" : "Metadata only"));
      const inspect = element("button", "button secondary", "Inspect");
      inspect.type = "button";
      inspect.addEventListener("click", () => loadActivityDetail(run.id));
      row.append(time, route, status, inspect);
      list.append(row);
    });
  } catch (error) { notify(error.message, true); }
}

async function loadActivityDetail(id) {
  try {
    const record = await api(`/activity/${encodeURIComponent(id)}`);
    const panel = $("activity-detail");
    panel.replaceChildren(element("h2", null, "Request record"));
    panel.hidden = false;
    addDetail(panel, "Recorded", formatDate(record.created_at));
    addDetail(panel, "Chosen path", routeLabel(record.route));
    if (record.policy_id) addDetail(panel, "Policy revision", record.policy_id);
    addDetail(panel, "Status", humanize(record.status || "Recorded"));
    const content = record.content || {};
    const result = content.result || {};
    const messages = content.messages || [];
    const prompt = record.prompt || content.prompt || messages.filter((message) => message.role === "user").map((message) => message.content || message.text || "").join("\n\n");
    const answer = record.answer || content.answer || result.answer;
    const payload = record.payload || content.payload || result.payload;
    if (prompt || answer || payload) {
      for (const [label, value] of [["Saved request", prompt], ["Saved answer", answer], ["Saved payload", payload]]) {
        if (!value) continue;
        panel.append(element("div", "detail-label", label), element("div", "activity-content", value));
      }
    } else panel.append(element("p", "field-help", "This record contains metadata only. The original request and answer are not available from this saved record."));
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) { notify(error.message, true); }
}

async function changeStorageSetting() {
  const desired = $("save-content").checked;
  $("save-content").disabled = true;
  try {
    await api("/settings", { method: "PATCH", body: { save_content: desired } });
    await refreshStatus(true);
    notify(desired ? "Future request and answer bodies will be saved locally. Existing records are unchanged." : "Future records will contain metadata only. Previously saved content remains until you delete it.");
  } catch (error) {
    $("save-content").checked = !desired;
    notify(error.message, true);
  } finally { $("save-content").disabled = false; }
}

async function deleteHistory() {
  if (!window.confirm("Delete all saved local request records and content? This cannot be undone. Provider-side records are unaffected.")) return;
  try {
    await api("/activity", { method: "DELETE" });
    state.conversation = null;
    $("chat-transcript").querySelectorAll(".chat-message").forEach((message) => message.remove());
    $("chat-empty").hidden = false;
    $("conversation-label").textContent = "New conversation";
    $("run-details-content").replaceChildren(element("p", "muted", "Details appear after your first request."));
    $("run-details").open = false;
    $("activity-detail").hidden = true;
    await loadActivity();
    notify("Local history was deleted and the conversation was cleared. Your next request starts a new conversation.");
  } catch (error) { notify(error.message, true); }
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
document.querySelectorAll("[data-open-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.openView)));
$("chat-form").addEventListener("submit", submitPrompt);
$("prompt-input").addEventListener("input", updateControls);
$("prompt-input").addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !$("submit-prompt").disabled) {
    event.preventDefault();
    $("chat-form").requestSubmit();
  }
});
$("destination").addEventListener("change", updateControls);
$("stop-run").addEventListener("click", cancelRun);
$("new-chat").addEventListener("click", newConversation);
$("refresh-models").addEventListener("click", refreshModels);
$("unload-model").addEventListener("click", async () => {
  $("unload-model").disabled = true;
  try {
    await api("/models/unload", { method: "POST", body: {} });
    await refreshStatus(true);
    notify("The active model was unloaded to release memory. Its downloaded files remain available; choose Use to activate it again.");
  } catch (error) { notify(error.message, true); updateControls(); }
});
$("model-search-form").addEventListener("submit", (event) => { event.preventDefault(); searchCatalog(); });
$("model-search").addEventListener("input", () => {
  clearTimeout(state.catalogTimer);
  state.catalogTimer = setTimeout(searchCatalog, 550);
});
$("model-sort").addEventListener("change", searchCatalog);
$("model-format").addEventListener("change", () => {
  state.modelDetails = null; state.selectedVariant = null;
  $("model-format-label").textContent = `LIVE CATALOG / ${$("model-format").value.toUpperCase()}`;
  $("model-detail").replaceChildren(element("div", "model-detail-empty", "Choose a repository to inspect its files."));
  searchCatalog();
});
$("pause-install").addEventListener("click", pauseInstall);
$("resume-install").addEventListener("click", resumeInstall);
$("cancel-install").addEventListener("click", cancelInstall);
$("retry-install").addEventListener("click", () => installModel(state.lastInstallModel));
$("advanced-model-form").addEventListener("submit", (event) => {
  event.preventDefault();
  installModel($("advanced-model-tag").value.trim());
});
$("policy-form").addEventListener("submit", compilePolicy);
$("policy-text").addEventListener("input", () => {
  state.policyDirty = true;
  state.draft = null;
  $("policy-state").textContent = "UNREVIEWED DRAFT";
  $("activate-policy").hidden = true;
  updateControls();
});
$("activate-policy").addEventListener("click", activatePolicy);
document.querySelectorAll(".provider-form").forEach((form) => form.addEventListener("submit", configureProvider));
for (const provider of ["openai", "anthropic", "remote"]) $(provider + "-model").addEventListener("input", () => state.providerDirty.add(provider));
document.querySelectorAll(".provider-disconnect").forEach((button) => button.addEventListener("click", () => disconnectProvider(button.dataset.provider)));
$("refresh-activity").addEventListener("click", loadActivity);
$("save-content").addEventListener("change", changeStorageSetting);
$("delete-history").addEventListener("click", deleteHistory);

function updateClock() {
  $("desk-clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function initialize() {
  updateClock();
  setInterval(updateClock, 30000);
  try {
    const session = await api("/session");
    state.token = session.token;
    await refreshStatus();
    setInterval(() => refreshStatus(true), 12000);
  } catch (error) {
    setOnline(false);
    notify(error.message, true);
  }
}

initialize();
