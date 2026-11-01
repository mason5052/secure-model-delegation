"""App-owned MLX model downloads and authenticated headless inference."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

import httpx

from .hub import HubCatalog, validate_repo_id
from .runtime import ManagedRuntime, RuntimeSetupError, CONTEXT_TOKENS


class ManagedMLX:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir / "mlx"
        self.models = self.data_dir / "models"
        self.models.mkdir(parents=True, exist_ok=True)
        self.selected = None
        self.process = None
        self.port = None
        self.token = secrets.token_urlsafe(32)
        self.state_path = self.data_dir / "selection.json"
        with contextlib.suppress(OSError, ValueError):
            self.selected = json.loads(self.state_path.read_text()).get("model")

    def model_path(self, model: str) -> Path:
        repo = validate_repo_id(model.removeprefix("mlx:"))
        return self.models / repo.replace("/", "--")

    def command(self) -> list[str]:
        helper = os.environ.get("SMD_MLX_PYTHON")
        if not helper or not Path(helper).is_file():
            raise RuntimeSetupError("The MLX engine is not present in this build. Use the complete desktop distribution.")
        if Path(helper).name == "smd-mlx-runtime":
            return [helper]
        return [helper, "-c", "from omlx.cli import main; main()"]

    async def start(self):
        if self.process and self.process.returncode is None:
            return
        command = self.command()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        environment = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT"}}
        environment.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1", "OMLX_BASE_PATH": str(self.data_dir / "server")})
        self.process = await asyncio.create_subprocess_exec(*command, "serve", "--model-dir", str(self.models), "--base-path", str(self.data_dir / "server"), "--host", "127.0.0.1", "--port", str(self.port), "--api-key", self.token, "--headless", "--no-cache", "--log-level", "error", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=environment)
        for _ in range(120):
            if self.process.returncode is not None:
                break
            try:
                await self.request("GET", "/v1/models")
                return
            except (httpx.HTTPError, RuntimeError):
                await asyncio.sleep(.25)
        await self.stop()
        raise RuntimeSetupError("The bundled MLX engine could not start. Check memory and OS compatibility.")

    async def request(self, method, path, **kwargs):
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(180, connect=3), follow_redirects=False) as client:
            response = await client.request(method, f"http://127.0.0.1:{self.port}" + path, headers={"Authorization": "Bearer " + self.token}, **kwargs)
            if response.status_code >= 300:
                raise RuntimeSetupError(f"The local MLX engine returned HTTP {response.status_code}. Check the model's supported capabilities.")
            return response.json()

    async def catalog(self, query="", sort="lastModified"):
        data = await HubCatalog()._get("/api/models", {"filter": "mlx", "search": query, "sort": sort, "direction": -1, "limit": 24, "full": "true", "cardData": "true"})
        from .hub import _license
        return {"models": [{"id": x["id"], "name": x["id"].split("/")[-1], "author": x["id"].split("/")[0], "format": "MLX", "downloads": x.get("downloads"), "last_modified": x.get("lastModified"), "license": _license(x), "compatibility": "not_checked", "description": "MLX architecture, task and memory compatibility are checked when loaded."} for x in data], "source": "Hugging Face", "cached": False, "offline": False, "scope": "Public MLX repositories; capability varies by model."}

    async def details(self, repo):
        repo = validate_repo_id(repo)
        data = await HubCatalog()._get("/api/models/" + repo, {"blobs": "true"})
        allowed = [x for x in data.get("siblings", []) if x.get("rfilename", "").endswith((".json", ".safetensors", ".model", ".txt", ".tiktoken", ".jinja"))]
        size = sum(x.get("size") or x.get("lfs", {}).get("size", 0) for x in allowed)
        ready = data.get("gated") is False and not data.get("private") and bool(data.get("sha")) and any(x["rfilename"].endswith(".safetensors") for x in allowed)
        return {"id": repo, "revision": data.get("sha"), "format": "MLX", "license": data.get("cardData", {}).get("license"), "variants": [{"id": repo, "filename": repo, "quantization": "Repository", "size_bytes": size, "size_gb": round(size / 1e9, 3), "model_ref": "mlx:" + repo, "installable": ready, "reason": None if ready else "Select public ungated MLX weights with a pinned revision.", "compatibility": "not_checked"}], "files": allowed, "reason": None, "note": "Model code is never downloaded or trusted. Tool and vision support depend on the architecture and chat template."}

    async def install(self, model, emit):
        # Engine availability is checked before downloading potentially large weights.
        self.command()
        repo = validate_repo_id(model.removeprefix("mlx:"))
        details = await self.details(repo)
        if not details["variants"][0]["installable"]:
            raise RuntimeSetupError(details["variants"][0]["reason"])
        target = self.model_path(model)
        target.mkdir(parents=True, exist_ok=True)
        total = details["variants"][0]["size_bytes"]
        if total > shutil.disk_usage(target).free - 512 * 1024**2:
            raise RuntimeSetupError("There is not enough free disk space for this model.")
        downloaded = 0
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(90, connect=10)) as client:
            for item in details["files"]:
                name = item["rfilename"]
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts or "\\" in name:
                    raise RuntimeSetupError("The repository contains an unsafe model path.")
                path = target.joinpath(*parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                size = item.get("size") or item.get("lfs", {}).get("size", 0)
                expected = item.get("lfs", {}).get("sha256")
                if path.exists() and path.stat().st_size == size and (not expected or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() == expected):
                    downloaded += size
                    continue
                partial = path.with_name(path.name + ".partial")
                offset = partial.stat().st_size if partial.exists() else 0
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                url = f"https://huggingface.co/{repo}/resolve/{details['revision']}/{name}"
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code not in {200, 206}:
                        raise RuntimeSetupError(f"Model download returned HTTP {response.status_code}. Retry to resume.")
                    append = response.status_code == 206 and offset > 0
                    if not append:
                        offset = 0
                    with partial.open("ab" if append else "wb") as output:
                        written = offset
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            written += len(chunk)
                            if size and written > size:
                                raise RuntimeSetupError("A model file exceeded its declared size.")
                            output.write(chunk)
                            await emit({"stage": "download", "message": "Downloading selected MLX weights.", "completed": downloaded + written, "total": total})
                if size and partial.stat().st_size != size:
                    raise RuntimeSetupError("The download is incomplete; retry to resume.")
                if expected:
                    with partial.open("rb") as handle:
                        if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                            partial.unlink()
                            raise RuntimeSetupError("Model integrity check failed. Download the file again.")
                partial.replace(path)
                downloaded += size
        (target / "smd-receipt.json").write_text(json.dumps({"repo": repo, "revision": details["revision"], "size_bytes": total}))
        if self.process and self.process.returncode is None:
            await self.stop()
            await self.start()
        return {"model": "mlx:" + repo, "installed": True, "selected": False}

    async def select(self, model):
        path = self.model_path(model)
        if not (path / "smd-receipt.json").is_file():
            raise RuntimeSetupError("Download this model first.")
        await self.start()
        await self.request("POST", "/v1/chat/completions", json={"model": path.name, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 16, "stream": False})
        self.selected = model
        self.state_path.write_text(json.dumps({"model": model}))
        return await self.status()

    async def status(self):
        installed = []
        for path in self.models.glob("*/smd-receipt.json"):
            with contextlib.suppress(ValueError, OSError):
                installed.append("mlx:" + json.loads(path.read_text())["repo"])
        return {"engine": "omlx", "runtime_version": "0.7.3", "runtime_installed": bool(os.environ.get("SMD_MLX_PYTHON")), "ready": bool(self.selected and self.process and self.process.returncode is None), "model": self.selected, "models": [{"name": x, "model": x, "selected": x == self.selected} for x in installed], "installed_models": installed, "cache_enabled": False}

    async def complete(self, body):
        await self.start()
        request = {**body, "model": self.model_path(self.selected).name, "stream": False}
        return await self.request("POST", "/v1/chat/completions", json=request)

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 8)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None


class LocalRuntimes:
    """Preserve the existing CLI runtime contract while adding model-format adapters."""
    def __init__(self, data_dir):
        self.ollama = ManagedRuntime(data_dir)
        self.mlx = ManagedMLX(data_dir)
        self.selection = data_dir / "active-engine.json"
        self.engine = "ollama"
        with contextlib.suppress(OSError, ValueError):
            self.engine = json.loads(self.selection.read_text()).get("engine", "ollama")

    async def start(self):
        await self.ollama.start()
        if self.engine == "mlx" and self.mlx.selected:
            await self.mlx.start()

    async def stop(self):
        await asyncio.gather(self.ollama.stop(), self.mlx.stop(), return_exceptions=True)

    async def status(self):
        status = await (self.mlx.status() if self.engine == "mlx" else self.ollama.status())
        other = await (self.ollama.status() if self.engine == "mlx" else self.mlx.status())
        status["models"] = status.get("models", []) + other.get("models", [])
        status["installed_models"] = list(dict.fromkeys(status.get("installed_models", []) + other.get("installed_models", [])))
        status["engines"] = {"ollama": {"available": True}, "mlx": {"available": bool(os.environ.get("SMD_MLX_PYTHON")), "minimum_macos": "15.0"}}
        return status

    async def install(self, model, emit):
        return await (self.mlx.install(model, emit) if model.startswith("mlx:") else self.ollama.install(model, emit))

    async def select(self, model):
        if model.startswith("mlx:") and self.ollama._model and self.ollama._port:
            with contextlib.suppress(RuntimeError, httpx.HTTPError):
                await self.ollama._request("POST", "/api/generate", json={"model": self.ollama._model, "keep_alive": 0})
        elif not model.startswith("mlx:"):
            await self.mlx.stop()
        result = await (self.mlx.select(model) if model.startswith("mlx:") else self.ollama.select(model))
        self.engine = "mlx" if model.startswith("mlx:") else "ollama"
        self.selection.write_text(json.dumps({"engine": self.engine}))
        return result

    async def remove(self, model):
        if model.startswith("mlx:"):
            if self.mlx.selected == model:
                await self.mlx.stop()
                self.mlx.selected = None
                self.mlx.state_path.unlink(missing_ok=True)
            shutil.rmtree(self.mlx.model_path(model))
        else:
            await self.ollama.remove(model)

    async def unload(self):
        if self.engine == "mlx":
            await self.mlx.stop()
            self.mlx.selected = None
            self.mlx.state_path.unlink(missing_ok=True)
        else:
            await self.ollama._stop_process()
            self.ollama._model, self.ollama._digest = None, None
            self.ollama._verified = False
            self.ollama._save_state()
        return await self.status()

    async def chat(self, messages, *, schema=None, temperature=0, max_tokens=1024):
        if self.engine != "mlx":
            if schema is not None and len(json.dumps(messages, ensure_ascii=False).encode()) + max_tokens + 512 > CONTEXT_TOKENS:
                if not self.ollama._verified:
                    raise RuntimeSetupError("Select and verify a local model first.")
                response = await self.ollama._request("POST", "/api/chat", json={
                    "model": self.ollama._model, "messages": messages, "format": schema,
                    "stream": False, "truncate": False, "think": False,
                    "options": {"num_ctx": 32768, "temperature": temperature, "num_predict": max_tokens}})
                content = response.get("message", {}).get("content", "")
                if response.get("done_reason") == "length":
                    raise RuntimeSetupError("Structured inspection reached its output limit; external delegation remains disabled.")
                json.loads(content)
                return content
            return await self.ollama.chat(messages, schema=schema, temperature=temperature, max_tokens=max_tokens)
        body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "smd", "schema": schema}}
        return (await self.mlx.complete(body))["choices"][0]["message"].get("content", "")

    async def agent_complete(self, body):
        if self.engine == "mlx":
            return await self.mlx.complete(body)
        if not self.ollama._verified:
            raise RuntimeSetupError("Select and verify a local model first.")
        messages = []
        for original in body["messages"]:
            message = {k: v for k, v in original.items() if k in {"role", "name", "tool_call_id", "tool_calls"}}
            if message["role"] == "developer":
                message["role"] = "system"
            content = original.get("content") or ""
            if isinstance(content, list):
                message["content"] = "\n".join(p["text"] for p in content if p["type"] == "text")
                images = [p["image_url"]["url"].split(",", 1)[1] for p in content if p["type"] == "image_url"]
                if images:
                    message["images"] = images
            else:
                message["content"] = content
            if message.get("tool_calls"):
                message["tool_calls"] = json.loads(json.dumps(message["tool_calls"]))
                for call in message["tool_calls"]:
                    call["function"]["arguments"] = json.loads(call["function"]["arguments"])
            messages.append(message)
        prepared = {"model": self.ollama._model, "messages": messages, "stream": False, "truncate": False,
                    "options": {"num_ctx": 32768, "num_predict": min(8192, body.get("max_tokens", body.get("max_completion_tokens", 2048))), "temperature": body.get("temperature", 0)}}
        if body.get("tools"):
            prepared["tools"] = body["tools"]
        if self.ollama._think.get(self.ollama._model) is False:
            prepared["think"] = False
        if body.get("response_format", {}).get("type") == "json_schema":
            prepared["format"] = body["response_format"]["json_schema"]["schema"]
        # The engine tokenizes the complete chat template with truncation disabled.
        # A JSON byte estimate would incorrectly reject ordinary tool-result turns.
        response = await self.ollama._request("POST", "/api/chat", json=prepared)
        message = response.get("message", {})
        content = message.get("content", "")
        if isinstance(content, str) and (self.ollama._model in getattr(self.ollama, "_qwen_models", set()) or "qwen3" in self.ollama._model.lower()):
            closing = re.search(r"(?m)^[ \t]*</think>[ \t]*(?:\r?\n|$)", content)
            if closing:
                message["content"] = content[closing.end():].strip()
            elif content.lstrip().startswith("<think>") and "</think>" in content:
                message["content"] = content.split("</think>", 1)[1].strip()
        for call in message.get("tool_calls", []):
            if not call.get("id"):
                call["id"] = "call_" + uuid.uuid4().hex
            call.setdefault("type", "function")
            call["function"]["arguments"] = json.dumps(call["function"]["arguments"], ensure_ascii=False)
        finish = "tool_calls" if message.get("tool_calls") else ("length" if response.get("done_reason") == "length" else "stop")
        message.pop("thinking", None)
        return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()), "model": body["model"], "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": {"prompt_tokens": response.get("prompt_eval_count", 0), "completion_tokens": response.get("eval_count", 0)}}
