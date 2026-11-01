"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const node = (tag, cls, text) => {
    const item = document.createElement(tag);
    if (cls) item.className = cls;
    if (text !== undefined) item.textContent = String(text);
    return item;
  };
  const work = {
    projects: [], project: null, sessions: [], session: null, tabs: [], split: null,
    folder: "", editor: null, messages: [], status: {}, currentJob: null,
    terminalJob: null, events: null, poll: null, voice: null, speaking: false, busy: false, runs: new Map(),
  };
  if (window.smdDesktop?.configureProvider) {
    document.querySelectorAll(".provider-form").forEach((form) => {
      const key = form.querySelector('input[name="api_key"]');
      if (key) { key.required = false; key.hidden = true; const label = document.querySelector(`label[for="${key.id}"]`); if (label) label.hidden = true; }
      const note = node("p", "field-help", "Connect opens a private Mac key-entry dialog. The API key is not entered into this page."); form.insertBefore(note, form.querySelector(".button-row"));
    });
  }
  const prefix = "/workspace";
  const ws = (path, options) => api(prefix + path, options);
  const enc = encodeURIComponent;
  const showError = (error) => notify(error.message || "The operation could not be completed.", true);
  const action = (button, handler) => button.addEventListener("click", () => Promise.resolve().then(handler).catch(showError));
  const jsonText = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2);

  function downloadBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const anchor = node("a");
    anchor.href = url;
    anchor.download = name;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function ask(title, fields, submitLabel = "Save") {
    return new Promise((resolve) => {
      const dialog = byId("desktop-dialog");
      const body = byId("dialog-fields");
      body.replaceChildren();
      byId("dialog-title").textContent = title;
      byId("dialog-submit").textContent = submitLabel;
      byId("dialog-error").hidden = true;
      const controls = new Map();
      for (const field of fields) {
        const label = node("label", "field-label", field.label);
        label.htmlFor = `dialog-${field.name}`;
        let input;
        if (field.type === "textarea") input = node("textarea", field.code ? "structure-editor" : "");
        else if (field.options) {
          input = node("select");
          for (const [value, text] of field.options) {
            const option = node("option", "", text); option.value = value; input.append(option);
          }
        } else {
          input = node("input"); input.type = field.type || "text";
        }
        input.id = label.htmlFor;
        input.name = field.name;
        if (field.value !== undefined || !field.options) input.value = field.value ?? "";
        if (field.type === "checkbox") input.checked = Boolean(field.value);
        else input.required = Boolean(field.required);
        if (field.type === "textarea") input.rows = field.rows || 6;
        if (field.placeholder) input.placeholder = field.placeholder;
        if (field.readonly) input.readOnly = true;
        body.append(label, input);
        if (field.help) body.append(node("p", "field-help", field.help));
        controls.set(field.name, input);
      }
      const finish = (value) => { dialog.close(); resolve(value); };
      byId("dialog-cancel").onclick = () => finish(null);
      byId("dialog-form").onsubmit = (event) => {
        event.preventDefault();
        finish(Object.fromEntries([...controls].map(([key, input]) => [key, input.type === "checkbox" ? input.checked : input.value])));
      };
      dialog.oncancel = (event) => { event.preventDefault(); finish(null); };
      dialog.showModal();
      const first = controls.values().next().value;
      if (first) first.focus();
    });
  }

  function projectPath(path = "") { return `/projects/${enc(work.project.id)}${path}`; }
  function sessionPath(path = "") { return `/sessions/${enc(work.session.id)}${path}`; }
  function button(text, handler, cls = "button secondary small-button") {
    const item = node("button", cls, text); item.type = "button"; action(item, handler); return item;
  }
  function empty(parent, title, description) {
    parent.replaceChildren(node("strong", "", title), node("p", "field-help", description));
  }
  function safeDate(value) {
    const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  async function refreshWorkspace() {
    const result = await ws("/status");
    work.status = result;
    const projects = await ws("/projects");
    work.projects = projects.projects || [];
    renderProjects();
    if (work.project && !work.projects.some((p) => p.id === work.project.id)) await selectProject(null);
    const capability = result.agent || {};
    byId("work-help").textContent = capability.available
      ? "Changes and commands always ask first. Full context follows your active information policy."
      : "The agent engine is not ready. Quick Chat and project file tools remain available.";
    updateRunControls();
  }

  function renderProjects() {
    const select = byId("project-select");
    select.replaceChildren();
    const start = node("option", "", "Choose a project"); start.value = ""; select.append(start);
    for (const project of work.projects) {
      const option = node("option", "", project.name + (project.archived ? " (Archived)" : "")); option.value = project.id; select.append(option);
    }
    select.value = work.project?.id || "";
    byId("project-settings").disabled = !work.project;
    byId("project-path").textContent = work.project?.folder || work.project?.path || "";
    byId("work-empty").hidden = Boolean(work.project);
    byId("work-area").hidden = !work.project;
    byId("work-tools").hidden = !work.project;
  }

  async function makeProject(folder = null) {
    if (folder) {
      const name = folder.replace(/[\\/]$/, "").split(/[\\/]/).pop() || "Project";
      const project = await ws("/projects", { method: "POST", body: { name, folder, save_content: false } });
      work.projects.push(project);
      await selectProject(project.id);
      return;
    }
    const values = await ask("New Project", [
      { name: "name", label: "Project name", required: true, placeholder: "Research notes" },
      { name: "folder", label: "Existing folder (optional)", help: "Leave blank for an app-managed workspace. Use Open folder for the Mac folder chooser." },
      { name: "save_content", label: "Save conversation bodies on this computer", type: "checkbox", value: false, help: "Off keeps only metadata after this app closes. Project files are stored separately." },
    ], "Create project");
    if (!values) return;
    const project = await ws("/projects", { method: "POST", body: { name: values.name, save_content: values.save_content, ...(values.folder.trim() ? { folder: values.folder.trim() } : {}) } });
    work.projects.push(project);
    await selectProject(project.id);
  }

  async function openProject() {
    if (!window.smdDesktop?.chooseFolder) {
      notify("The Mac folder chooser is available in the desktop app. You can enter a folder path in New project.");
      return makeProject();
    }
    const result = await window.smdDesktop.chooseFolder();
    const path = typeof result === "string" ? result : result.paths?.[0] || result.path;
    if (path && !result.canceled) await makeProject(path);
  }

  async function selectProject(id) {
    work.project = work.projects.find((p) => p.id === id) || null;
    try { if (work.project) localStorage.setItem("smd.project", work.project.id); else localStorage.removeItem("smd.project"); } catch (_) {}
    work.session = null; work.sessions = []; work.tabs = []; work.split = null; work.folder = ""; work.editor = null;
    byId("file-editor").value = "";
    byId("file-editor").disabled = true;
    byId("editor-save").disabled = true;
    renderProjects();
    if (!work.project) return;
    await loadSessions();
    const savedTabs = (work.project.tabs || []).map((tab) => typeof tab === "string" ? tab : tab.id).filter(Boolean);
    work.tabs = savedTabs.filter((tab) => work.sessions.some((s) => s.id === tab));
    if (!work.sessions.length) await makeSession();
    else await selectSession(work.tabs[0] || work.sessions[0].id);
    await loadFiles();
    byId("terminal-output").textContent = "Commands run here only after you approve them.";
    showView("work");
  }

  async function projectSettings() {
    if (!work.project) return;
    const values = await ask("Project Settings", [
      { name: "name", label: "Project name", value: work.project.name, required: true },
      { name: "folder", label: "Folder", value: work.project.folder || "", readonly: true },
      { name: "save_content", label: "Save future conversation content", type: "checkbox", value: work.project.save_content, help: "Turning this off removes saved conversation bodies for this project. Active session context remains in memory until the app closes." },
      { name: "archived", label: "Archive this project", type: "checkbox", value: work.project.archived },
      { name: "delete_project", label: "Delete this project record and its sessions", type: "checkbox", value: false, help: "Project files are preserved. Deleting saved session records cannot be undone." },
    ]);
    if (!values) return;
    if (values.delete_project) {
      if (!window.confirm("Delete this project record and its saved sessions? Project files will be preserved. This cannot be undone.")) return;
      await ws(projectPath(), { method: "DELETE" });
      work.projects = work.projects.filter((project) => project.id !== work.project.id); await selectProject(null); renderProjects(); return;
    }
    if (work.project.save_content && !values.save_content && !window.confirm("Turning content saving off removes previously saved conversation bodies for this project. Continue?")) return;
    const updated = await ws(projectPath(), { method: "PATCH", body: { name: values.name, save_content: values.save_content, archived: values.archived } });
    work.projects = work.projects.map((p) => p.id === updated.id ? updated : p); work.project = updated;
    if (values.archived) await selectProject(null);
    renderProjects();
  }

  async function loadSessions() {
    if (!work.project) return;
    const query = byId("session-search").value.trim();
    const result = await ws(projectPath(`/sessions?query=${enc(query)}`));
    work.sessions = result.sessions || [];
    const list = byId("session-list"); list.replaceChildren();
    if (!work.sessions.length) empty(list, "No sessions", "Create a session for this task.");
    for (const session of work.sessions) {
      const item = node("button", `session-row${session.id === work.session?.id ? " selected" : ""}`);
      item.type = "button";
      item.append(node("strong", "", session.title || "Untitled session"), node("small", "", `${session.archived ? "Archived / " : ""}${safeDate(session.updated_at || session.created_at)}${session.save_content ? " / Saved" : ""}`));
      action(item, () => selectSession(session.id)); list.append(item);
    }
    renderTabs();
  }

  async function makeSession() {
    if (!work.project) return;
    const session = await ws(projectPath("/sessions"), { method: "POST", body: { title: "New task" } });
    work.sessions.unshift(session);
    await selectSession(session.id);
    await loadSessions();
    byId("work-prompt").focus();
  }

  async function persistTabs() {
    if (!work.project) return;
    await ws(projectPath(), { method: "PATCH", body: { tabs: work.tabs.map((id) => ({ id, type: "session" })) } });
  }

  async function selectSession(id) {
    work.session = await ws(`/sessions/${enc(id)}`);
    if (!work.tabs.includes(id)) { work.tabs.push(id); await persistTabs(); }
    const context = await ws(`/sessions/${enc(id)}/messages`);
    work.messages = context.messages || [];
    work.contextMissing = Boolean(context.previous_content_unavailable);
    byId("session-context-warning").hidden = !work.contextMissing;
    byId("session-context-warning").textContent = "Earlier conversation bodies were not saved. This session can continue, but its previous content has not been restored.";
    byId("work-session-title").textContent = work.session.title || "Untitled session";
    byId("pin-session").textContent = work.session.pinned ? "Unpin" : "Pin";
    for (const key of ["split-session", "fork-session", "rename-session", "archive-session", "export-session", "pin-session", "delete-session"]) byId(key).disabled = false;
    renderTranscript(byId("work-transcript"), work.messages);
    renderTabs();
    await loadSessions();
    updateRunControls();
  }

  function renderTabs() {
    const tabs = byId("session-tabs"); tabs.replaceChildren();
    for (const id of work.tabs) {
      const session = work.sessions.find((s) => s.id === id) || (work.session?.id === id ? work.session : null);
      if (!session) continue;
      const tab = node("div", `session-tab${id === work.session?.id ? " selected" : ""}`);
      const open = button(session.title || "Untitled", () => selectSession(id), "tab-label");
      open.setAttribute("role", "tab"); open.setAttribute("aria-selected", String(id === work.session?.id));
      const close = button("x", async () => {
        work.tabs = work.tabs.filter((tabId) => tabId !== id);
        if (work.session?.id === id && work.tabs.length) await selectSession(work.tabs[work.tabs.length - 1]);
        await persistTabs(); renderTabs();
      }, "tab-close");
      close.setAttribute("aria-label", `Close ${session.title || "session"} tab`);
      tab.append(open, close); tabs.append(tab);
    }
  }

  function messageText(message) {
    if (typeof message.content === "string") return message.content;
    if (Array.isArray(message.content)) return message.content.map((part) => part.text || (part.type === "image_url" ? "[Image attachment]" : jsonText(part))).join("\n");
    if (Array.isArray(message.parts)) return message.parts.map((part) => part.text || (part.type === "tool" ? `[Tool: ${part.tool || part.name || "operation"}]\n${part.state?.output || part.state?.status || ""}` : "")).filter(Boolean).join("\n");
    return message.text || "";
  }

  function renderTranscript(container, messages) {
    container.replaceChildren();
    if (!messages.length) {
      const intro = node("div", "session-start");
      intro.append(node("span", "document-glyph", "aethon"), node("h2", "", "Start with the task."), node("p", "", "Work with the files in this project. Review every proposed change and command before it runs."));
      container.append(intro); return;
    }
    for (const message of messages) {
      const role = message.role || message.info?.role || "assistant";
      const row = node("article", `work-message role-${role}`);
      const heading = node("div", "message-heading");
      heading.append(node("strong", "", role === "user" ? "You" : role === "tool" ? "Tool result" : "Assistant"));
      if (message.created_at) heading.append(node("small", "muted", safeDate(message.created_at)));
      row.append(heading, node("div", "message-body", messageText(message)));
      container.append(row);
    }
    container.scrollTop = container.scrollHeight;
  }

  async function renameSession() {
    const values = await ask("Rename Session", [{ name: "title", label: "Title", value: work.session.title, required: true }]);
    if (!values) return;
    work.session = await ws(sessionPath(), { method: "PATCH", body: values });
    byId("work-session-title").textContent = work.session.title;
    await loadSessions();
  }

  async function archiveSession() {
    if (!window.confirm("Archive this session? Its saved content will remain on this computer.")) return;
    await ws(sessionPath(), { method: "PATCH", body: { archived: true } });
    await loadSessions(); notify("Session archived.");
  }

  async function pinSession() {
    work.session = await ws(sessionPath(), { method: "PATCH", body: { pinned: !work.session.pinned } });
    byId("pin-session").textContent = work.session.pinned ? "Unpin" : "Pin";
    await loadSessions();
  }

  async function deleteSession() {
    if (!window.confirm("Delete this session and its saved conversation content? This cannot be undone.")) return;
    const deleted = work.session.id;
    await ws(sessionPath(), { method: "DELETE" });
    work.tabs = work.tabs.filter((id) => id !== deleted); work.session = null;
    await loadSessions();
    if (work.sessions.length) await selectSession(work.sessions[0].id); else await makeSession();
  }

  async function forkSession() {
    const next = await ws(sessionPath("/fork"), { method: "POST", body: {} });
    work.sessions.push(next);
    await selectSession(next.id); notify("Created a branch with the conversation available in this session.");
  }

  async function splitSession() {
    const pane = byId("split-transcript");
    if (!pane.hidden) { pane.hidden = true; byId("session-panels").classList.remove("split"); byId("split-session").textContent = "Split view"; return; }
    work.split = work.session.id;
    renderTranscript(pane, work.messages);
    pane.prepend(node("div", "split-caption", `Reference: ${work.session.title || "Session"}`));
    pane.hidden = false; byId("session-panels").classList.add("split"); byId("split-session").textContent = "Close split";
  }

  function updateRunControls() {
    const current = work.session ? work.runs.get(work.session.id) : null;
    byId("work-submit").disabled = !state.online || !work.session || !work.status.agent?.available || !isReady() || Boolean(current);
    byId("work-stop").hidden = !current;
    byId("agent-progress").hidden = !current;
    if (current) byId("agent-progress").textContent = current.message || "Task running...";
    if (!isReady()) byId("work-help").textContent = "Select a local model in Models to begin. File tools remain available.";
  }

  async function runTask(event) {
    event.preventDefault();
    if (!work.session || work.runs.has(work.session.id)) return;
    const prompt = byId("work-prompt").value.trim();
    if (!prompt) return;
    const sessionId = work.session.id;
    const running = { job_id: null, message: "Preparing the complete context and active policy...", parts: new Map() };
    work.runs.set(sessionId, running);
    updateRunControls();
    byId("agent-progress").hidden = false; byId("agent-progress").textContent = "Preparing the complete context and active policy...";
    work.messages.push({ role: "user", content: prompt }); renderTranscript(byId("work-transcript"), work.messages);
    try {
      const result = await ws(`/sessions/${enc(sessionId)}/run`, { method: "POST", body: { prompt, model: byId("work-destination").value === "local" ? "smd-local" : `smd-${byId("work-destination").value}` } });
      byId("work-prompt").value = "";
      running.job_id = result.job_id || result.id;
      await watchJob(running.job_id, (record) => {
        if (record.message) running.message = record.message;
        else if (record.type) running.message = humanize(record.type);
        if (record.type === "approval" && record.approval) showApproval(record.approval);
        if (record.type === "agent" && record.event) {
          const event = record.event;
          const props = event.properties || {};
          if (event.type === "message.part.updated" && props.part?.type === "text") running.parts.set(props.part.id || "text", props.part.text || "");
          if (event.type === "message.part.delta" && props.field === "text") running.parts.set(props.partID || "text", (running.parts.get(props.partID || "text") || "") + (props.delta || ""));
          if (event.type === "permission.asked") running.message = "Waiting for your approval...";
        }
        if (work.session?.id === sessionId) {
          updateRunControls();
          const partial = [...running.parts.values()].join("\n");
          if (partial) renderTranscript(byId("work-transcript"), [...work.messages, { role: "assistant", content: partial }]);
        }
      });
      if (work.session?.id === sessionId) {
        work.messages = (await ws(`/sessions/${enc(sessionId)}/messages`)).messages || [];
        renderTranscript(byId("work-transcript"), work.messages);
      }
      await loadSessions();
    } catch (error) { showError(error); }
    finally {
      work.runs.delete(sessionId);
      updateRunControls();
    }
  }

  async function watchJob(id, onEvent = () => {}) {
    return new Promise((resolve, reject) => {
      const stream = new EventSource(`/api/v1/workspace/jobs/${enc(id)}/events`);
      let settled = false;
      const finish = (error, record) => { if (settled) return; settled = true; stream.close(); clearInterval(timer); error ? reject(error) : resolve(record); };
      const accept = (record) => {
        onEvent(record);
        if (["completed", "complete", "succeeded"].includes(record.type) || ["completed", "complete", "succeeded"].includes(record.status)) finish(null, record);
        if (["failed", "error", "cancelled", "canceled"].includes(record.type) || ["failed", "error", "cancelled", "canceled"].includes(record.status)) finish(new Error(record.error || record.message || "Operation stopped."));
      };
      stream.onmessage = (event) => { try { accept(JSON.parse(event.data)); } catch (error) { if (error instanceof SyntaxError) return; finish(error); } };
      stream.onerror = () => { /* Polling also handles a terminal event lost during reconnect. */ };
      const timer = setInterval(async () => {
        try { const record = await ws(`/jobs/${enc(id)}`); accept(record); } catch (error) { finish(error); }
      }, 1500);
    });
  }

  async function loadFiles() {
    if (!work.project) return;
    const result = await ws(projectPath(`/files?path=${enc(work.folder)}`));
    byId("file-path").textContent = result.path || "/";
    const list = byId("file-list"); list.replaceChildren();
    for (const file of result.entries || []) {
      const isDirectory = file.type === "directory" || file.is_dir || file.directory;
      const item = button("", async () => {
        const path = file.path || [work.folder, file.name].filter(Boolean).join("/");
        if (isDirectory) { work.folder = path; await loadFiles(); } else await openFile(path);
      }, "file-row");
      item.append(node("span", `file-glyph${isDirectory ? " folder" : ""}`, isDirectory ? "+" : "="), node("span", "file-name", file.name));
      list.append(item);
    }
    if (!list.childElementCount) empty(list, "Empty folder", "Create a file or ask the agent to prepare one.");
  }

  function workTool(name) {
    document.querySelectorAll("[data-work-tool]").forEach((tab) => tab.classList.toggle("selected", tab.dataset.workTool === name));
    document.querySelectorAll(".work-tool").forEach((panel) => { panel.hidden = panel.id !== `tool-${name}`; });
  }

  async function openFile(path) {
    if (/\.(docx|xlsx|pptx|pdf)$/i.test(path)) { await inspectDocument(path); return; }
    const file = await ws(projectPath(`/file?path=${enc(path)}`));
    work.editor = file;
    byId("editor-title").textContent = file.path;
    byId("file-editor").value = file.content || ""; byId("file-editor").disabled = false;
    byId("editor-save").disabled = false; byId("editor-state").textContent = "No changes";
    byId("editor-diff").hidden = true;
    workTool("editor");
  }

  async function saveFile() {
    if (!work.project || !work.editor) return;
    const content = byId("file-editor").value;
    const result = await ws(projectPath("/file"), { method: "POST", body: { path: work.editor.path, content, base_sha256: work.editor.sha256, ...(work.session ? { session_id: work.session.id } : {}) } });
    byId("editor-state").textContent = "Waiting for your approval";
    if (result.approval?.details?.diff) { byId("editor-diff").textContent = result.approval.details.diff; byId("editor-diff").hidden = false; }
    showApproval(result.approval);
  }

  async function newFile() {
    if (!work.project) throw new Error("Choose a project first.");
    const values = await ask("New Project File", [
      { name: "path", label: "Relative file path", value: work.folder ? `${work.folder}/notes.md` : "notes.md", required: true },
      { name: "content", label: "Contents", type: "textarea", rows: 10 },
    ], "Review creation");
    if (!values) return;
    const result = await ws(projectPath("/file"), { method: "POST", body: values });
    showApproval(result.approval);
  }

  async function runCommand(event) {
    event.preventDefault();
    if (!work.project) throw new Error("Choose a project first.");
    const command = byId("terminal-command").value.trim();
    if (!command) return;
    const result = await ws(projectPath("/commands"), { method: "POST", body: { command, ...(work.session ? { session_id: work.session.id } : {}) } });
    showApproval(result.approval);
  }

  function showApproval(approval) {
    if (!approval?.id) return;
    const list = byId("work-approvals");
    let card = document.getElementById(`approval-${approval.id}`);
    if (card) return;
    card = node("article", "approval-card"); card.id = `approval-${approval.id}`;
    const header = node("div", "approval-heading");
    header.append(node("span", "approval-symbol", "?"), node("strong", "", "Your approval is required"), node("span", "tiny-tag", humanize(approval.kind)));
    card.append(header, node("p", "", approval.summary || "Review this operation before it runs."));
    const detail = node("details"); const summary = node("summary", "", "Inspect proposed operation");
    detail.append(summary, node("pre", "approval-detail", jsonText(approval.details || {}))); card.append(detail);
    const buttons = node("div", "button-row");
    for (const [allowed, text] of [[false, "Deny"], [true, "Approve once"]]) buttons.append(button(text, async () => {
      buttons.querySelectorAll("button").forEach((item) => { item.disabled = true; });
      try {
        const result = await ws(`/approvals/${enc(approval.id)}/decision`, { method: "POST", body: { approved: allowed } });
        card.remove();
        if (result.job_id) {
          const isCommand = /command|shell|exec/i.test(approval.kind || "");
          if (isCommand) { work.terminalJob = result.job_id; byId("terminal-stop").disabled = false; byId("terminal-output").textContent = `$ ${approval.details?.command || "approved command"}\n`; workTool("terminal"); }
          try {
            const final = await watchJob(result.job_id, (event) => {
              if (isCommand) {
                if (event.output || event.stdout || event.stderr || (event.type === "output" && event.text)) byId("terminal-output").textContent += String(event.output || event.stdout || event.stderr || event.text);
                if (event.result?.stdout || event.result?.output) byId("terminal-output").textContent = String(event.result.stdout || event.result.output);
              }
            });
            if (isCommand) {
              const output = final.result?.stdout || final.result?.output;
              if (output) byId("terminal-output").textContent = String(output);
            } else if (final.result) {
              const resultRow = node("article", "work-message role-tool");
              resultRow.append(node("strong", "", "Approved tool result"), node("pre", "approval-detail", jsonText(final.result)));
              byId("work-transcript").append(resultRow);
            }
          } finally { if (isCommand) { work.terminalJob = null; byId("terminal-stop").disabled = true; } }
        }
        if (allowed && work.project) {
          await loadFiles();
          if (work.editor && /file|document/i.test(approval.kind || "")) await openFile(work.editor.path);
        }
        notify(allowed ? "Approved operation completed or started. Its status is shown in the workspace." : "Operation denied. Nothing was executed.");
      } catch (error) { card.remove(); throw error; }
    }, allowed ? "button primary small-button" : "button secondary small-button"));
    card.append(buttons); list.append(card);
    showView("work");
  }

  async function refreshApprovals() {
    if (!state.online) return;
    const result = await ws("/approvals");
    const pending = (result.approvals || []).filter((item) => item.status === "pending" || item.status === "requested");
    document.querySelectorAll(".approval-card").forEach((card) => {
      if (!pending.some((item) => card.id === `approval-${item.id}`)) card.remove();
    });
    for (const approval of pending) showApproval(approval);
  }

  const structures = {
    docx: { paragraphs: ["Document title", "Write the first paragraph here."], tables: [] },
    xlsx: { sheets: [{ name: "Sheet1", rows: [["Item", "Value"], ["Example", 10]] }] },
    pptx: { slides: [{ title: "Presentation title", body: ["Write the slide text here."] }] },
    md: { text: "# New document\n\nWrite here.\n" },
    html: { text: "<!doctype html><html><body><h1>New document</h1><p>Write here.</p></body></html>" },
    csv: { rows: [["Item", "Value"], ["Example", 10]] },
    txt: { text: "Write here.\n" },
  };

  async function createDocument() {
    if (!work.project) throw new Error("Choose a project first.");
    const values = await ask("New Document", [
      { name: "format", label: "Format", options: [["docx", "Word document (.docx)"], ["xlsx", "Spreadsheet (.xlsx)"], ["pptx", "Presentation (.pptx)"], ["md", "Markdown (.md)"], ["html", "HTML (.html)"], ["csv", "CSV (.csv)"], ["txt", "Plain text (.txt)"]] },
      { name: "name", label: "File name without extension", value: "untitled", required: true },
    ], "Continue");
    if (!values) return;
    await editDocument(`${values.name}.${values.format}`, values.format, structures[values.format], null);
  }

  async function editDocument(path, format, structure, sha256) {
    const values = await ask(`Edit ${path}`, [
      { name: "path", label: "Relative file path", value: path, required: true },
      { name: "structure", label: "Document structure", type: "textarea", code: true, rows: 15, value: jsonText(structure), help: "Edit the named fields. This structure editor preserves the format shown here; it is not a full Office layout editor." },
    ], "Review & write");
    if (!values) return;
    let parsed;
    try { parsed = JSON.parse(values.structure); } catch (_) { throw new Error("The document structure must be valid JSON. No file was changed."); }
    const result = await ws(projectPath("/document"), { method: "POST", body: { path: values.path, format, structure: parsed, ...(sha256 ? { base_sha256: sha256 } : {}) } });
    showApproval(result.approval);
  }

  async function showPdfPreview(path, renderUrl = null) {
    const urlPath = renderUrl || `/api/v1/workspace/projects/${enc(work.project.id)}/download?path=${enc(path)}`;
    if (renderUrl && !/^\/api\/v1\/workspace\/renders\/[a-f0-9]+$/.test(renderUrl)) throw new Error("The preview returned an unsupported local address.");
    const response = await fetch(urlPath, { credentials: "same-origin" });
    if (!response.ok) throw new Error("The PDF preview could not be opened.");
    const buffer = await response.arrayBuffer();
    const signature = new TextDecoder().decode(new Uint8Array(buffer).subarray(0, 5));
    if (signature !== "%PDF-") throw new Error("The renderer did not return a PDF document.");
    const viewer = await import("/static/pdf/preview.js");
    await viewer.renderPdf(byId("document-preview"), new Uint8Array(buffer));
  }

  async function inspectDocument(path = null) {
    if (!work.project) throw new Error("Choose a project first.");
    if (!path) {
      const values = await ask("Inspect Project Document", [{ name: "path", label: "Relative file path", required: true, placeholder: "report.docx" }], "Open");
      if (!values) return; path = values.path;
    }
    workTool("documents");
    const panel = byId("document-content"); panel.replaceChildren(node("h3", "", path));
    if (/\.pdf$/i.test(path)) {
      await showPdfPreview(path);
      return;
    }
    byId("document-preview").hidden = true;
    const doc = await ws(projectPath(`/document?path=${enc(path)}`));
    panel.append(node("pre", "document-structure", jsonText(doc.structure)));
    const buttons = node("div", "button-row");
    buttons.append(button("Edit structure", () => editDocument(path, doc.format, doc.structure, doc.sha256)));
    const link = node("a", "button secondary small-button", "Download original");
    link.href = `/api/v1/workspace/projects/${enc(work.project.id)}/download?path=${enc(path)}`; link.download = path.split("/").pop(); buttons.append(link);
    if (["docx", "xlsx", "pptx"].includes(doc.format)) buttons.append(button("Preview as PDF", async () => {
      const result = await ws(projectPath("/render"), { method: "POST", body: { path } });
      const final = await watchJob(result.job_id);
      const previewUrl = final.result?.download_url || final.download_url;
      const previewPath = final.result?.path || final.path;
      if (!previewUrl && !previewPath) throw new Error("The renderer did not return a PDF address.");
      await showPdfPreview(previewPath, previewUrl);
    }));
    panel.append(buttons);
  }

  async function loadExtensions() {
    const [skills, mcp] = await Promise.all([ws("/skills"), ws("/mcp")]);
    const skillList = byId("skill-list"); skillList.replaceChildren();
    for (const skill of skills.skills || []) {
      const item = node("div", "extension-row");
      item.append(node("strong", "", skill.name), node("span", "tiny-tag", skill.enabled ? "ENABLED" : "OFF"));
      const actions = node("div", "button-row");
      actions.append(button("Inspect", async () => {
        const values = await ask(skill.name, [{ name: "content", label: "SKILL.md", type: "textarea", value: skill.content || "", rows: 14 }, { name: "enabled", label: "Enable instructions", type: "checkbox", value: skill.enabled }]);
        if (values) { await ws(`/skills/${enc(skill.id)}`, { method: "PATCH", body: values }); await loadExtensions(); }
      }), button("Remove", async () => {
        if (!confirm(`Remove ${skill.name}?`)) return;
        await ws(`/skills/${enc(skill.id)}`, { method: "DELETE" }); await loadExtensions();
      }));
      item.append(actions); skillList.append(item);
    }
    if (!skillList.childElementCount) empty(skillList, "No installed skills", "Add reviewed SKILL.md instructions to reuse them.");
    const mcpList = byId("mcp-list"); mcpList.replaceChildren();
    for (const server of mcp.servers || []) {
      const item = node("div", "extension-row");
      item.append(node("strong", "", server.name), node("small", "mono", server.transport === "stdio" ? jsonText(server.command || []) : server.url), node("span", "tiny-tag", server.enabled ? "ENABLED" : "OFF"));
      const actions = node("div", "button-row");
      actions.append(button(server.enabled ? "Disable" : "Enable", async () => { await ws(`/mcp/${enc(server.id)}`, { method: "PATCH", body: { enabled: !server.enabled } }); await loadExtensions(); }), button("Discover tools", async () => { const result = await ws(`/mcp/${enc(server.id)}/discover`, { method: "POST" }); showApproval(result.approval); }), button("Remove", async () => { if (!confirm(`Remove ${server.name}?`)) return; await ws(`/mcp/${enc(server.id)}`, { method: "DELETE" }); await loadExtensions(); }));
      item.append(actions);
      for (const tool of server.tools || []) item.append(button(tool.name, async () => {
        const values = await ask(`Call ${tool.name}`, [{ name: "arguments", label: "Tool arguments (JSON)", type: "textarea", value: "{}", rows: 6 }], "Review call");
        if (!values) return;
        let args; try { args = JSON.parse(values.arguments); } catch (_) { throw new Error("Tool arguments must be valid JSON."); }
        const result = await ws(`/mcp/${enc(server.id)}/call`, { method: "POST", body: { name: tool.name, arguments: args } }); showApproval(result.approval);
      }));
      mcpList.append(item);
    }
    if (!mcpList.childElementCount) empty(mcpList, "No tool servers", "Add a server explicitly. Existing system configurations are not imported automatically.");
  }

  async function addSkill() {
    const values = await ask("Add Skill", [{ name: "name", label: "Name", required: true }, { name: "content", label: "SKILL.md contents", type: "textarea", value: "---\nname: my-skill\ndescription: Describe when to use this skill.\n---\n\nWrite the instructions here.\n", rows: 12 }, { name: "enabled", label: "Enable after adding", type: "checkbox", value: false }], "Add skill");
    if (values) { await ws("/skills", { method: "POST", body: values }); await loadExtensions(); }
  }

  async function addMcp() {
    const values = await ask("Add MCP Server", [
      { name: "name", label: "Name", required: true },
      { name: "transport", label: "Transport", options: [["stdio", "Local process (stdio)"], ["http", "HTTP server"]] },
      { name: "command", label: "Executable and arguments (JSON array)", placeholder: '["/absolute/path/to/server", "argument"]' },
      { name: "url", label: "HTTP URL", placeholder: "http://127.0.0.1:8080/mcp" },
    ], "Add disabled server");
    if (!values) return;
    const payload = { name: values.name, transport: values.transport, enabled: false };
    if (values.transport === "stdio") { try { payload.command = JSON.parse(values.command); } catch (_) { throw new Error("The command must be a JSON array of executable and arguments."); } }
    else payload.url = values.url;
    await ws("/mcp", { method: "POST", body: payload }); await loadExtensions();
  }

  async function readWeb(event) {
    event.preventDefault();
    const url = byId("web-address").value.trim();
    if (!url) return;
    const panel = byId("web-result"); panel.replaceChildren(node("p", "", "Checking and reading this public page..."));
    try {
      const result = await api("/web/read", { method: "POST", body: { url } });
      panel.replaceChildren(node("h2", "", result.title || "Public page"));
      const source = node("a", "source-link", result.url || url); source.href = result.url || url; source.target = "_blank"; source.rel = "noopener noreferrer";
      panel.append(source, node("div", "web-page-text", result.text || result.content || jsonText(result)));
    } catch (error) { panel.replaceChildren(node("p", "error", error.message)); }
  }

  async function searchVoice(event) {
    event.preventDefault();
    byId("voice-status").textContent = "Searching Hugging Face for local speech models...";
    try {
      const result = await api(`/voice/catalog?query=${enc(byId("voice-query").value.trim())}`);
      const select = byId("voice-model"); select.replaceChildren();
      const blank = node("option", "", "Choose a model"); blank.value = ""; select.append(blank);
      for (const model of result.models || []) { const option = node("option", "", model.name || model.id); option.value = model.id; select.append(option); }
      byId("voice-status").textContent = `${(result.models || []).length} candidates. Speech format, architecture, and memory compatibility vary by model.`;
    } catch (error) { byId("voice-status").textContent = error.message; }
  }

  async function configureSearch(event) {
    event.preventDefault();
    const url = byId("web-provider-url").value.trim();
    await api("/web/search-provider", { method: "PUT", body: { url } });
    notify("Search endpoint connected for this app session. Search queries follow your active information policy.");
  }

  async function searchWeb(event) {
    event.preventDefault();
    const panel = byId("web-result"); panel.replaceChildren(node("p", "", "Checking and searching..."));
    try {
      const result = await api("/web/search", { method: "POST", body: { query: byId("web-search-query").value.trim() } });
      panel.replaceChildren(node("h2", "", "Search results"));
      for (const item of result.results || []) {
        const row = node("article", "web-search-result");
        row.append(button(item.title || item.url, async () => { byId("web-address").value = item.url; await readWeb({ preventDefault() {} }); }, "source-title"), node("small", "mono", item.url), node("p", "", item.content || ""));
        panel.append(row);
      }
      if (!(result.results || []).length) panel.append(node("p", "muted", "No results were returned by your search provider."));
    } catch (error) { panel.replaceChildren(node("p", "error", error.message)); }
  }

  async function loadAgentActivity() {
    const result = await api("/agent/activity");
    const list = byId("agent-activity-list"); list.replaceChildren();
    for (const record of result.runs || []) {
      const row = node("details", "agent-audit-row");
      const heading = node("summary");
      heading.append(node("strong", "", routeLabel(record.route)), node("span", "", humanize(record.destination)), node("small", "muted", new Date(typeof record.created_at === "number" ? record.created_at * 1000 : record.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
      row.append(heading);
      for (const [label, value] of [["Policy clauses", record.rule_ids], ["Decision reasons", record.reasons], ["Inspection", record.inspection], ["Request hash", record.request_hash], ["Outbound body hash", record.outbound_hash]]) {
        if (value === undefined || value === null) continue;
        row.append(node("div", "detail-label", label), node("pre", "approval-detail", jsonText(value)));
      }
      row.append(node("p", "field-help", record.external_attempted ? "An external request was attempted on this path." : "No external model request was attempted on this path."));
      if (record.payload) row.append(node("div", "detail-label", "Body passed to the provider adapter"), node("pre", "approval-detail", jsonText(record.payload)));
      list.append(row);
    }
    if (!list.childElementCount) empty(list, "No completed agent calls yet", "Records appear as agent model requests finish.");
  }

  async function voiceStatus() {
    try {
      const result = await api("/voice/status");
      result.ready = result.ready ?? Boolean(result.available && result.selected_model);
      const description = result.ready ? `Ready: ${result.model || "local speech model"}` : result.message || "Search, choose, and download a supported speech model.";
      byId("voice-status").textContent = description;
      if (result.model) {
        const choice = byId("voice-model");
        if (![...choice.options].some((option) => option.value === result.model)) { const option = node("option", "", result.model); option.value = result.model; choice.append(option); }
        choice.value = result.model;
      }
      return result;
    } catch (error) { byId("voice-status").textContent = error.message; return null; }
  }

  async function installVoice() {
    const model = byId("voice-model").value.trim();
    if (!model) throw new Error("Enter a supported speech model repository first.");
    byId("voice-status").textContent = "Downloading selected speech model...";
    const result = await api("/voice/install", { method: "POST", body: { model } });
    if (result.id || result.job_id) {
      const id = result.id || result.job_id;
      await new Promise((resolve, reject) => {
        const events = new EventSource(`/api/v1/jobs/${enc(id)}/events`);
        events.onmessage = (event) => {
          const record = JSON.parse(event.data); byId("voice-status").textContent = record.message || "Downloading speech model...";
          if (record.type === "completed") { events.close(); resolve(); }
          if (record.type === "failed") { events.close(); reject(new Error(record.error || "Speech model download failed.")); }
        };
        events.onerror = () => { events.close(); reject(new Error("Speech model setup connection stopped. Check status before retrying.")); };
      });
    }
    await voiceStatus();
  }

  async function transcribeBlob(blob, filename = "recording.wav") {
    if (blob.size > 15 * 1024 * 1024) throw new Error("Choose an audio file smaller than 15 MB.");
    byId("work-voice").textContent = "Transcribing..."; byId("work-voice").disabled = true;
    try {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let raw = ""; for (let at = 0; at < bytes.length; at += 8192) raw += String.fromCharCode(...bytes.subarray(at, at + 8192));
      const result = await api("/voice/transcribe", { method: "POST", body: { audio_base64: btoa(raw), filename } });
      const values = await ask("Review Dictation", [{ name: "text", label: "Transcribed text", type: "textarea", value: result.text || result.transcript || "", rows: 8, help: "This text has not been submitted to a model." }], "Use in task");
      if (values) { showView("work"); byId("work-prompt").value += (byId("work-prompt").value ? "\n" : "") + values.text; byId("work-prompt").focus(); }
    } finally { byId("work-voice").textContent = "Dictate"; byId("work-voice").disabled = false; }
  }

  function wavBlob(samples, sampleRate) {
    const length = samples.reduce((sum, chunk) => sum + chunk.length, 0);
    const buffer = new ArrayBuffer(44 + length * 2); const view = new DataView(buffer);
    const write = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
    write(0, "RIFF"); view.setUint32(4, 36 + length * 2, true); write(8, "WAVE"); write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, length * 2, true);
    let offset = 44; for (const chunk of samples) for (const sample of chunk) { view.setInt16(offset, Math.max(-1, Math.min(1, sample)) * 0x7fff, true); offset += 2; }
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function dictate() {
    if (work.voice) {
      const recording = work.voice; work.voice = null;
      recording.processor.disconnect(); recording.source.disconnect(); recording.stream.getTracks().forEach((track) => track.stop());
      await recording.context.close(); clearTimeout(recording.timeout);
      await transcribeBlob(wavBlob(recording.samples, recording.sampleRate)); return;
    }
    const readiness = await voiceStatus();
    if (!readiness?.ready) { showView("extensions"); notify("Set up a local speech model before recording."); return; }
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Microphone access is unavailable. You can transcribe a local audio file in Extensions.");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    const context = new AudioContext(); const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1); const samples = [];
    processor.onaudioprocess = (event) => { samples.push(new Float32Array(event.inputBuffer.getChannelData(0))); event.outputBuffer.getChannelData(0).fill(0); };
    source.connect(processor); processor.connect(context.destination);
    const timeout = setTimeout(() => { if (work.voice) dictate().catch(showError); }, 120000);
    work.voice = { stream, context, source, processor, samples, sampleRate: context.sampleRate, timeout };
    byId("work-voice").textContent = "Stop recording";
  }

  async function readAnswer() {
    if (work.speaking) {
      if (window.smdDesktop?.stopSpeaking) await window.smdDesktop.stopSpeaking();
      if (window.speechSynthesis) speechSynthesis.cancel();
      work.speaking = false; byId("read-answer").textContent = "Read aloud"; return;
    }
    const text = [...work.messages].reverse().find((message) => (message.role || message.info?.role) === "assistant");
    const content = text ? messageText(text) : "";
    if (!content) throw new Error("There is no assistant answer to read yet.");
    work.speaking = true; byId("read-answer").textContent = "Stop reading";
    if (window.smdDesktop?.speak) await window.smdDesktop.speak(content.slice(0, 10000));
    else if (window.speechSynthesis) { speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(content); utterance.onend = () => { work.speaking = false; byId("read-answer").textContent = "Read aloud"; }; speechSynthesis.speak(utterance); }
    else throw new Error("Local text-to-speech is unavailable on this device.");
  }

  async function loadCanvas() {
    if (window.smdCanvas) return;
    try {
      const stylesheet = document.createElement("link"); stylesheet.rel = "stylesheet"; stylesheet.href = "/static/canvas/canvas.css"; document.head.append(stylesheet);
      await import("/static/canvas/canvas.js");
    }
    catch (_) { byId("canvas-host").replaceChildren(node("p", "error", "The bundled drawing module could not be loaded. Rebuild the desktop assets and restart the app.")); }
  }

  async function initializeDesktop() {
    while (!state.token) await new Promise((resolve) => setTimeout(resolve, 100));
    showView("work");
    if (window.smdDesktop?.hardware) {
      try { state.hardware = await window.smdDesktop.hardware(); } catch (_) {}
    }
    await refreshWorkspace().catch(showError);
    try { const remembered = localStorage.getItem("smd.project"); if (remembered && work.projects.some((project) => project.id === remembered)) await selectProject(remembered); } catch (_) {}
    setInterval(() => { if (state.online) refreshApprovals().catch(() => {}); }, 1500);
    setInterval(() => {
      const destination = byId("work-destination"); const previous = destination.value;
      destination.replaceChildren(...[...byId("destination").options].map((option) => option.cloneNode(true)));
      if ([...destination.options].some((option) => option.value === previous)) destination.value = previous;
      updateRunControls();
    }, 3000);
    if (window.smdDesktop?.onWorkspaceSelected) window.smdDesktop.onWorkspaceSelected((value) => makeProject(typeof value === "string" ? value : value.path || value.paths?.[0]).catch(showError));
  }

  for (const [id, handler] of Object.entries({ "new-project": () => makeProject(), "open-project": openProject, "project-settings": projectSettings, "new-session": makeSession, "pin-session": pinSession, "delete-session": deleteSession, "rename-session": renameSession, "archive-session": archiveSession, "fork-session": forkSession, "split-session": splitSession, "editor-save": saveFile, "new-file": newFile, "refresh-files": loadFiles, "document-create": createDocument, "document-open": () => inspectDocument(), "refresh-extensions": loadExtensions, "add-skill": addSkill, "add-mcp": addMcp, "voice-install": installVoice, "voice-refresh": voiceStatus, "work-voice": dictate, "read-answer": readAnswer })) action(byId(id), handler);
  byId("project-select").addEventListener("change", () => selectProject(byId("project-select").value).catch(showError));
  byId("session-search").addEventListener("input", () => { clearTimeout(work.poll); work.poll = setTimeout(() => loadSessions().catch(showError), 300); });
  action(byId("export-session"), () => downloadBlob(new Blob([JSON.stringify({ title: work.session.title, previous_content_unavailable: Boolean(work.contextMissing), messages: work.messages }, null, 2)], { type: "application/json" }), `${work.session.title || "session"}.json`));
  action(byId("sessions-tab"), () => { byId("session-pane").hidden = false; byId("file-pane").hidden = true; byId("sessions-tab").classList.add("selected"); byId("files-tab").classList.remove("selected"); });
  action(byId("files-tab"), () => { byId("session-pane").hidden = true; byId("file-pane").hidden = false; byId("sessions-tab").classList.remove("selected"); byId("files-tab").classList.add("selected"); return loadFiles(); });
  action(byId("files-up"), () => { work.folder = work.folder.split("/").slice(0, -1).join("/"); return loadFiles(); });
  byId("file-editor").addEventListener("input", () => { byId("editor-state").textContent = byId("file-editor").value === work.editor?.content ? "No changes" : "Unsaved changes"; });
  byId("work-form").addEventListener("submit", runTask);
  byId("work-prompt").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); byId("work-form").requestSubmit(); } });
  byId("terminal-form").addEventListener("submit", (event) => runCommand(event).catch(showError));
  action(byId("terminal-stop"), () => work.terminalJob && ws(`/jobs/${enc(work.terminalJob)}/cancel`, { method: "POST" }));
  action(byId("work-stop"), () => work.session && work.runs.has(work.session.id) && ws(sessionPath("/cancel"), { method: "POST" }));
  document.querySelectorAll("[data-work-tool]").forEach((item) => action(item, () => workTool(item.dataset.workTool)));
  document.querySelectorAll("[data-view]").forEach((item) => item.addEventListener("click", () => {
    if (item.dataset.view === "work") refreshWorkspace().catch(showError);
    if (item.dataset.view === "extensions") loadExtensions().catch(showError);
    if (item.dataset.view === "canvas") loadCanvas();
  }));
  byId("web-form").addEventListener("submit", readWeb);
  byId("web-provider-form").addEventListener("submit", (event) => configureSearch(event).catch(showError));
  byId("web-search-form").addEventListener("submit", searchWeb);
  byId("voice-search-form").addEventListener("submit", searchVoice);
  action(byId("voice-upload"), () => byId("voice-file").click());
  byId("voice-file").addEventListener("change", () => { const file = byId("voice-file").files[0]; if (file) transcribeBlob(file, file.name).catch(showError); byId("voice-file").value = ""; });
  action(byId("canvas-import"), () => byId("canvas-file").click());
  byId("canvas-file").addEventListener("change", async () => { try { await loadCanvas(); const file = byId("canvas-file").files[0]; if (file) await window.smdCanvas.open(await file.text()); } catch (error) { showError(error); } finally { byId("canvas-file").value = ""; } });
  document.querySelectorAll("[data-canvas-export]").forEach((item) => action(item, async () => { await loadCanvas(); if (!window.smdCanvas) throw new Error("Drawing tools are unavailable."); const result = await window.smdCanvas.export(item.dataset.canvasExport); downloadBlob(result.blob, result.name); }));
  let activeMenu = null;
  function closeMenu() { if (activeMenu) activeMenu.remove(); activeMenu = null; }
  const menuActions = {
    file: [["New project...", () => makeProject()], ["Open folder...", openProject], ["New session", () => work.project ? makeSession() : makeProject()], ["Export session", () => { if (!work.session) throw new Error("Select a session first."); byId("export-session").click(); }]],
    edit: [["Information policy", () => showView("policy")], ["Find sessions", () => { showView("work"); byId("session-search").focus(); }], ["Read last answer", readAnswer]],
    view: [["Workspace", () => showView("work")], ["Quick Chat", () => showView("chat")], ["Model Manager", () => { showView("models"); }], ["Canvas", async () => { showView("canvas"); await loadCanvas(); }], ["Web", () => showView("browser")], ["Extensions", async () => { showView("extensions"); await loadExtensions(); }]],
    window: [["Split session", () => { if (!work.session) throw new Error("Select a session first."); showView("work"); return splitSession(); }], ["Activity & storage", () => showView("activity")]],
  };
  document.querySelectorAll("[data-desktop-menu]").forEach((item) => item.addEventListener("click", (event) => {
    event.stopPropagation();
    const wasOpen = activeMenu?.dataset.menu === item.dataset.desktopMenu;
    closeMenu(); if (wasOpen) return;
    const popup = node("div", "desktop-menu"); popup.dataset.menu = item.dataset.desktopMenu; popup.setAttribute("role", "menu");
    popup.style.left = `${item.getBoundingClientRect().left}px`;
    for (const [label, handler] of menuActions[item.dataset.desktopMenu]) popup.append(button(label, async () => { closeMenu(); await handler(); }, "desktop-menu-item"));
    document.body.append(popup); activeMenu = popup;
  }));
  document.addEventListener("click", (event) => { if (activeMenu && !activeMenu.contains(event.target)) closeMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
  window.addEventListener("smd:activity", () => loadAgentActivity().catch(showError));
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") { event.preventDefault(); (work.project ? makeSession() : makeProject()).catch(showError); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s" && !byId("file-editor").disabled && state.activeView === "work") { event.preventDefault(); saveFile().catch(showError); }
  });
  window.addEventListener("beforeunload", () => { if (work.voice) work.voice.stream.getTracks().forEach((track) => track.stop()); if (window.speechSynthesis) speechSynthesis.cancel(); });
  window.smdWorkspace = { refresh: refreshWorkspace, openProject: makeProject, state: work, showView };
  initializeDesktop();
})();
