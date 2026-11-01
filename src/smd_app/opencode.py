"""Private OpenCode processes with a single SMD model provider and one-shot approvals."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import tempfile
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx


MODEL_ALIASES = ("smd-local", "smd-openai", "smd-anthropic", "smd-remote")
PLUGIN_VERSION = "1.19.5"
GUARD_MARKER = "aethon_workspace_boundary"


class AgentUnavailable(RuntimeError):
    pass


def prepare_workspace_guard(home: Path, folder: Path) -> None:
    """Install our first-party path guard in the otherwise empty plugin profile."""
    source = r'''
import fs from "node:fs/promises";
import path from "node:path";
import {tool} from "@opencode-ai/plugin";
const ROOT = __SMD_ROOT__;
const BLOCKED = new Set([".git", ".ssh", ".aws", ".gnupg", ".opencode", ".agents", ".claude"]);
const SKIP = new Set(["node_modules", ".venv", "venv", "__pycache__"]);
async function checked(value = ROOT) {
  if (typeof value !== "string" || value.includes("\0")) throw new Error("SMD: invalid workspace path");
  if (value.split(/[/\\]/).includes("..")) throw new Error("SMD: parent traversal is not permitted");
  if ((await fs.lstat(ROOT)).isSymbolicLink()) throw new Error("SMD: the workspace folder changed into a symbolic link");
  const candidate = path.resolve(ROOT, value);
  const relative = path.relative(ROOT, candidate);
  if (relative === ".." || relative.startsWith(".." + path.sep) || path.isAbsolute(relative))
    throw new Error("SMD: this path leaves the selected workspace");
  let cursor = ROOT;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    if (BLOCKED.has(segment)) throw new Error("SMD: workspace control directories are not accessible");
    cursor = path.join(cursor, segment);
    try {
      if ((await fs.lstat(cursor)).isSymbolicLink()) throw new Error("SMD: symbolic links are not followed");
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  return candidate;
}
function globRegex(pattern) {
  if (typeof pattern !== "string" || !pattern || pattern.length > 512 || pattern.includes("..") || path.isAbsolute(pattern))
    throw new Error("SMD: choose a relative workspace glob pattern");
  let result = "";
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === "*" && pattern[i + 1] === "*") {
      i++;
      if (pattern[i + 1] === "/") { i++; result += "(?:.*/)?"; } else result += ".*";
    } else if (ch === "*") result += "[^/]*";
    else if (ch === "?") result += "[^/]";
    else result += ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp("^" + result + "$");
}
async function* files(base) {
  const stack = [base]; let visited = 0;
  while (stack.length) {
    const current = await checked(stack.pop());
    const entries = await fs.readdir(current, {withFileTypes: true});
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      if (++visited > 30000) throw new Error("SMD: workspace search limit reached; choose a smaller folder");
      if (entry.isSymbolicLink() || BLOCKED.has(entry.name)) continue;
      const full = await checked(path.join(current, entry.name));
      if (entry.isDirectory()) { if (!SKIP.has(entry.name)) stack.push(full); }
      else if (entry.isFile()) yield full;
    }
  }
}
const location = tool.schema.string().max(4096).optional();
export const AethonWorkspace = async () => ({
  "tool.execute.before": async (input, output) => {
    const args = output.args || {};
    if (["read", "edit", "write", "multiedit"].includes(input.tool)) {
      await checked(args.filePath ?? args.path);
    }
    if (["glob", "grep", "list"].includes(input.tool)) await checked(args.path ?? ROOT);
    if (input.tool === "apply_patch") {
      const text = args.patchText ?? args.patch ?? "";
      const paths = [...text.matchAll(/^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$/gm)].map(m => m[1]);
      if (!paths.length) throw new Error("SMD: the patch has no reviewable file paths");
      for (const value of paths) await checked(value);
    }
  },
  tool: {
    aethon_workspace_boundary: tool({description: "Internal Aethon workspace boundary marker.", args: {}, execute: async () => "Active"}),
    glob: tool({
      description: "Find workspace files by a relative glob (*, ** and ?). Symbolic links and control directories are excluded.",
      args: {pattern: tool.schema.string().min(1).max(512), path: location},
      execute: async args => {
        const base = await checked(args.path ?? ROOT); const match = globRegex(args.pattern); const results = [];
        for await (const full of files(base)) {
          const relative = path.relative(base, full).split(path.sep).join("/");
          if (match.test(relative) || (!args.pattern.includes("/") && match.test(path.basename(full)))) results.push(full);
          if (results.length >= 500) return results.join("\n") + "\n[Result limit reached; narrow the pattern.]";
        }
        return results.length ? results.join("\n") : "No matching files in the searched workspace scope.";
      }
    }),
    grep: tool({
      description: "Search for literal text in workspace files. Regex syntax is not interpreted. Symbolic links and dependency folders are excluded.",
      args: {pattern: tool.schema.string().min(1).max(512), path: location, include: tool.schema.string().max(512).optional()},
      execute: async args => {
        const base = await checked(args.path ?? ROOT); const include = args.include ? globRegex(args.include) : null; const matches = [];
        for await (const full of files(base)) {
          const relative = path.relative(base, full).split(path.sep).join("/");
          if (include && !include.test(relative) && !include.test(path.basename(full))) continue;
          if ((await fs.stat(full)).size > 2 * 1024 * 1024) continue;
          const buffer = await fs.readFile(full); if (buffer.includes(0)) continue;
          const lines = buffer.toString("utf8").split(/\r?\n/);
          for (let i = 0; i < lines.length; i++) if (lines[i].includes(args.pattern)) {
            matches.push(full + ":" + (i + 1) + ":" + lines[i].slice(0, 1000));
            if (matches.length >= 200) return matches.join("\n") + "\n[Result limit reached; narrow the search.]";
          }
        }
        return matches.length ? matches.join("\n") : "No literal matches in the searched text-file scope.";
      }
    }),
    list: tool({
      description: "List one workspace folder without following symbolic links.",
      args: {path: location},
      execute: async args => {
        const base = await checked(args.path ?? ROOT); const entries = await fs.readdir(base, {withFileTypes:true});
        return entries.filter(e => !e.isSymbolicLink() && !BLOCKED.has(e.name)).slice(0, 500)
          .map(e => e.name + (e.isDirectory() ? "/" : "")).join("\n");
      }
    })
  }
});
'''.replace("__SMD_ROOT__", json.dumps(str(folder.resolve())))
    target = home / "config" / "opencode" / "plugins"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = target / "aethon-workspace.js"
    script.write_text(source)
    script.chmod(0o600)


def prepare_packaged_support(home: Path, support: Path) -> None:
    """Copy only packaged dependencies, never a user's configuration or auth files."""
    support = support.resolve()
    try:
        manifest = json.loads((support / "package.json").read_text())
    except (OSError, ValueError):
        raise AgentUnavailable("The packaged coding-agent support files are unavailable.") from None
    if manifest.get("dependencies") != {"@opencode-ai/plugin": PLUGIN_VERSION}:
        raise AgentUnavailable("The packaged coding-agent dependency version does not match this build.")
    modules = support / "node_modules"
    if not modules.is_dir() or not (support / "package-lock.json").is_file():
        raise AgentUnavailable("The packaged coding-agent dependencies are incomplete.")
    count, size = 0, 0
    for parent, directories, filenames in os.walk(modules, followlinks=False):
        for name in [*directories, *filenames]:
            candidate = Path(parent) / name
            count += 1
            try:
                candidate.resolve().relative_to(support)
            except (OSError, ValueError, RuntimeError):
                raise AgentUnavailable("A packaged coding-agent dependency leaves its support directory.") from None
            if candidate.is_file():
                size += candidate.stat().st_size
            if count > 30000 or size > 512 * 1024 * 1024:
                raise AgentUnavailable("The packaged coding-agent dependency set exceeds its size limit.")
    target = home / "config" / "opencode"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for filename in ("package.json", "package-lock.json"):
        shutil.copyfile(support / filename, target / filename)
    shutil.copytree(modules, target / "node_modules", symlinks=True)


def agent_configuration(gateway: dict) -> dict:
    url = urlsplit(gateway.get("base_url", ""))
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or not gateway.get("api_key"):
        raise AgentUnavailable("The private local SMD gateway is not configured.")
    model = gateway.get("model", "smd-local")
    if model not in MODEL_ALIASES:
        raise AgentUnavailable("Choose an SMD model route.")
    return {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False, "share": "disabled", "snapshot": False,
        "enabled_providers": ["smd"], "model": "smd/" + model,
        "small_model": "smd/smd-local", "plugin": [], "mcp": {},
        "provider": {"smd": {
            "npm": "@ai-sdk/openai-compatible", "name": "Secure Model Delegation",
            "options": {"baseURL": gateway["base_url"], "apiKey": gateway["api_key"]},
            "models": {name: {"name": name, "tool_call": True,
                              "limit": {"context": 32768, "output": 2048}} for name in MODEL_ALIASES},
        }},
        # Never use OpenCode's auto-approve mode. Every edit and command asks again.
        "permission": {"*": "deny", "read": "allow", "list": "allow", "glob": "allow",
                       "grep": "allow", "edit": "ask", "bash": "ask", "task": "ask",
                       "external_directory": "deny", "webfetch": "deny", "websearch": "deny",
                       "skill": "deny", "question": "deny"},
        "lsp": False, "formatter": False,
    }


def isolated_environment(home: Path, gateway: dict, password: str) -> dict:
    # Do not inherit model provider keys, user plugin paths, or proxy credentials.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "LANG", "LC_ALL")
           if key in os.environ}
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
                "OPENCODE_CONFIG_CONTENT": json.dumps(agent_configuration(gateway)),
                "OPENCODE_SERVER_USERNAME": "smd", "OPENCODE_SERVER_PASSWORD": password,
                "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                "OPENCODE_DISABLE_LSP_DOWNLOAD": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                "OPENCODE_DB": ":memory:",
                "DO_NOT_TRACK": "1", "NO_COLOR": "1"})
    return env


class OpenCodeServer:
    """One process for one explicitly selected project; no user OpenCode profile is reused."""

    def __init__(self, folder: Path, gateway: dict, binary: str | None = None):
        self.folder = folder.resolve()
        self.gateway = gateway
        self.binary = (binary or os.environ.get("SMD_OPENCODE_BINARY") or
                       os.environ.get("SMD_OPENCODE") or shutil.which("opencode"))
        self.process: asyncio.subprocess.Process | None = None
        self.client: httpx.AsyncClient | None = None
        self.home: tempfile.TemporaryDirectory | None = None
        self.event_task: asyncio.Task | None = None
        self.handlers: dict[str, Callable[[dict], Awaitable[None]]] = {}
        self.parents: dict[str, str] = {}
        self.sessions: dict[str, str] = {}
        self.start_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self.start_lock:
            if self.process is not None and self.process.returncode is None:
                return
            if not self.binary or not Path(self.binary).is_file():
                raise AgentUnavailable("The packaged coding agent is unavailable. Chat and document tools remain available.")
            agent_configuration(self.gateway)
            self.home = tempfile.TemporaryDirectory(prefix="smd-agent-")
            home = Path(self.home.name)
            home.chmod(0o700)
            support = os.environ.get("SMD_OPENCODE_SUPPORT_DIR")
            if support:
                try:
                    await asyncio.to_thread(prepare_packaged_support, home, Path(support))
                except Exception:
                    self.home.cleanup()
                    self.home = None
                    raise
            prepare_workspace_guard(home, self.folder)
            password = secrets.token_urlsafe(32)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            self.process = await asyncio.create_subprocess_exec(
                self.binary, "serve", "--hostname", "127.0.0.1", "--port", str(port),
                cwd=str(self.folder), env=isolated_environment(home, self.gateway, password),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name != "nt")
            self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                            auth=("smd", password), trust_env=False,
                                            timeout=httpx.Timeout(30, read=600))
            for _ in range(100):
                if self.process.returncode is not None:
                    await self.stop()
                    raise AgentUnavailable("The coding agent could not start with the private configuration.")
                try:
                    response = await self.client.get("/global/health", timeout=1)
                    if response.is_success and response.json().get("healthy"):
                        tools = await self.client.get("/experimental/tool/ids", params={"directory": str(self.folder)}, timeout=30)
                        if not tools.is_success or GUARD_MARKER not in tools.json():
                            await self.stop()
                            raise AgentUnavailable("The coding-agent workspace boundary could not be loaded.")
                        self.event_task = asyncio.create_task(self._events())
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                await asyncio.sleep(.1)
            await self.stop()
            raise AgentUnavailable("The coding agent did not become ready.")

    async def _events(self) -> None:
        try:
            async with self.client.stream("GET", "/event", timeout=None) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or len(line) > 1024 * 1024:
                        continue
                    try:
                        event = json.loads(line[6:])
                    except ValueError:
                        continue
                    properties = event.get("properties", {})
                    session_id = properties.get("sessionID") or properties.get("info", {}).get("sessionID")
                    if event.get("type") == "session.created":
                        info = properties.get("info", {})
                        child_id, parent_id = info.get("id"), info.get("parentID")
                        if child_id and parent_id:
                            self.parents[child_id] = parent_id
                            if parent_id in self.handlers:
                                self.handlers[child_id] = self.handlers[parent_id]
                    if event.get("type") in {"permission.asked", "permission.updated"}:
                        session_id = properties.get("sessionID")
                    handler = self.handlers.get(session_id)
                    if handler:
                        try:
                            await handler(event)
                        except Exception:
                            # A failed UI/validation callback must never turn a
                            # permission request into an implicit approval.
                            if event.get("type") in {"permission.asked", "permission.updated"} and properties.get("id"):
                                with contextlib.suppress(Exception):
                                    await self.reply(session_id, properties["id"], False)
                            with contextlib.suppress(Exception):
                                await handler({"type": "smd.tool_blocked", "properties": {
                                    "sessionID": session_id, "message": "The tool request could not be safely reviewed."}})
        except (httpx.HTTPError, asyncio.CancelledError):
            return

    async def session(self, local_id: str, title: str) -> str:
        await self.start()
        if local_id not in self.sessions:
            response = await self.client.post("/session", params={"directory": str(self.folder)}, json={"title": title})
            if not response.is_success:
                raise AgentUnavailable("The coding agent could not create a session.")
            self.sessions[local_id] = response.json()["id"]
        return self.sessions[local_id]

    async def run(self, local_id: str, title: str, prompt: str, model: str,
                  handler: Callable[[dict], Awaitable[None]], system: str = "") -> dict:
        if model not in MODEL_ALIASES:
            raise AgentUnavailable("Choose an SMD model route.")
        session_id = await self.session(local_id, title)
        self.handlers[session_id] = handler
        try:
            response = await self.client.post(f"/session/{session_id}/message", params={"directory": str(self.folder)}, json={
                "model": {"providerID": "smd", "modelID": model},
                "system": system,
                "parts": [{"type": "text", "text": prompt}],
            }, timeout=600)
            if not response.is_success:
                raise AgentUnavailable("The coding agent run failed. Inspect the SMD route and model capabilities.")
            body = response.json()
            if body.get("info", {}).get("error"):
                raise AgentUnavailable("The selected model could not complete this agent run.")
            text = "\n".join(part.get("text", "") for part in body.get("parts", []) if part.get("type") == "text")
            if not text.strip():
                raise AgentUnavailable("The coding agent returned no complete text answer. Inspect the tool results and selected model.")
            return {"answer": text, "agent_session_id": session_id}
        finally:
            for child in [key for key, callback in self.handlers.items() if callback is handler]:
                self.handlers.pop(child, None)

    async def reply(self, session_id: str, permission_id: str, approved: bool) -> None:
        if not self.client:
            raise AgentUnavailable("The coding agent is no longer running.")
        response = await self.client.post(f"/permission/{permission_id}/reply", json={
            "reply": "once" if approved else "reject"})
        if response.status_code == 404:
            response = await self.client.post(f"/session/{session_id}/permissions/{permission_id}", json={
                "response": "once" if approved else "reject", "remember": False})
        if not response.is_success:
            raise AgentUnavailable("This permission request expired or was already answered.")

    async def cancel(self, local_id: str) -> None:
        session_id = self.sessions.get(local_id)
        if self.client and session_id:
            with contextlib.suppress(httpx.HTTPError):
                await self.client.post(f"/session/{session_id}/abort", timeout=3)

    async def stop(self) -> None:
        if self.event_task:
            self.event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.event_task
            self.event_task = None
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGTERM)
                else:
                    self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    if os.name != "nt":
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                await self.process.wait()
        self.process = None
        if self.home:
            self.home.cleanup()
            self.home = None
