const promptInput = document.getElementById("promptInput");
const exampleSelect = document.getElementById("exampleSelect");
const processButton = document.getElementById("processButton");
const clearButton = document.getElementById("clearButton");
const healthStatus = document.getElementById("healthStatus");

const routeBadge = document.getElementById("routeBadge");
const utilityValue = document.getElementById("utilityValue");
const hardActionValue = document.getElementById("hardActionValue");
const transportValue = document.getElementById("transportValue");
const targetProfileValue = document.getElementById("targetProfileValue");
const advisoryRouteValue = document.getElementById("advisoryRouteValue");
const labelChips = document.getElementById("labelChips");
const reasonsList = document.getElementById("reasonsList");
const ruleIdsList = document.getElementById("ruleIdsList");
const spanTableBody = document.getElementById("spanTableBody");
const payloadPanel = document.getElementById("payloadPanel");
const leakagePanel = document.getElementById("leakagePanel");
const auditRef = document.getElementById("auditRef");
const externalRef = document.getElementById("externalRef");

let examples = [];

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    healthStatus.textContent = data.status === "ok" ? "API online" : "API unknown";
  } catch (error) {
    healthStatus.textContent = "API offline";
  }
}

async function loadExamples() {
  const response = await fetch("/api/examples");
  examples = await response.json();
  for (const example of examples) {
    const option = document.createElement("option");
    option.value = example.id;
    option.textContent = example.title;
    exampleSelect.appendChild(option);
  }
}

exampleSelect.addEventListener("change", () => {
  const selected = examples.find((item) => item.id === exampleSelect.value);
  if (selected) {
    promptInput.value = selected.prompt;
  }
});

clearButton.addEventListener("click", () => {
  promptInput.value = "";
  exampleSelect.value = "";
  resetResults();
});

processButton.addEventListener("click", async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert("Enter a synthetic prompt first.");
    return;
  }

  processButton.disabled = true;
  processButton.textContent = "Processing...";

  try {
    const response = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        case_id: "WEB_MANUAL_001",
        user_prompt: prompt,
        target_profile: "external_ai",
        transport: "simulated_external_endpoint",
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Request failed");
    }

    renderResult(await response.json());
  } catch (error) {
    alert(error.message);
  } finally {
    processButton.disabled = false;
    processButton.textContent = "Process";
  }
});

function resetResults() {
  routeBadge.textContent = "No run yet";
  routeBadge.className = "route-badge";
  utilityValue.textContent = "-";
  hardActionValue.textContent = "-";
  transportValue.textContent = "-";
  targetProfileValue.textContent = "-";
  advisoryRouteValue.textContent = "-";
  labelChips.innerHTML = "";
  reasonsList.innerHTML = "";
  ruleIdsList.innerHTML = "";
  spanTableBody.innerHTML = "";
  payloadPanel.textContent = "No external delegation";
  leakagePanel.textContent = "No direct leakage detected";
  leakagePanel.className = "leakage-ok";
  auditRef.textContent = "-";
  externalRef.textContent = "-";
}

function renderResult(result) {
  routeBadge.textContent = result.route;
  routeBadge.className = `route-badge ${routeClass(result.route)}`;
  utilityValue.textContent = result.utility_label || "-";
  hardActionValue.textContent = result.hard_action || "-";
  transportValue.textContent = result.transport || "-";
  targetProfileValue.textContent = result.target_profile || "-";
  advisoryRouteValue.textContent = result.advisory_route || "-";
  auditRef.textContent = result.audit_ref || "-";
  externalRef.textContent = result.external_ref || "-";

  renderChips(result.detected_labels || []);
  renderList(reasonsList, result.decision_reasons || []);
  renderList(ruleIdsList, result.rule_ids || []);
  renderSpanTable(result.detected_spans || []);

  payloadPanel.textContent = result.delegated_payload || "No external delegation";

  if (result.leakage_found && result.leakage_found.length) {
    leakagePanel.className = "leakage-alert";
    leakagePanel.textContent = result.leakage_found.join("\n");
  } else {
    leakagePanel.className = "leakage-ok";
    leakagePanel.textContent = "No direct leakage detected";
  }
}

function routeClass(route) {
  if (route && route.startsWith("delegate")) return "delegate";
  if (route === "deny_request") return "deny";
  if (route === "ask_clarification") return "clarify";
  if (route && route.startsWith("local")) return "local";
  return "";
}

function renderChips(labels) {
  labelChips.innerHTML = "";
  if (!labels.length) {
    labelChips.textContent = "None";
    return;
  }
  for (const label of labels) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = label;
    labelChips.appendChild(chip);
  }
}

function renderList(target, items) {
  target.innerHTML = "";
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "None";
    target.appendChild(item);
    return;
  }
  for (const value of items) {
    const item = document.createElement("li");
    item.textContent = value;
    target.appendChild(item);
  }
}

function renderSpanTable(spans) {
  spanTableBody.innerHTML = "";
  if (!spans.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = "No sensitive spans detected.";
    row.appendChild(cell);
    spanTableBody.appendChild(row);
    return;
  }

  for (const span of spans) {
    const row = document.createElement("tr");
    for (const key of ["label", "detector", "severity", "action", "start", "end", "preview"]) {
      const cell = document.createElement("td");
      cell.textContent = span[key] ?? "-";
      row.appendChild(cell);
    }
    spanTableBody.appendChild(row);
  }
}

resetResults();
loadHealth();
loadExamples();
