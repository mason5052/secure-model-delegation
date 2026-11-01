"""Application-owned, local-only Ollama runtime and model management."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

from .hub import HubCatalog, HubCatalogError, validate_repo_id


RUNTIME_VERSION = "0.40.13"
RELEASE_URL = "https://github.com/ollama/ollama/releases/download/v" + RUNTIME_VERSION
# Digests from the official v0.40.13 release, checked on October 31, 2026.
ASSETS = {
    "darwin-arm64": ("ollama-darwin.tgz", "bae29252232b9e1358cf5801a7d65a07442af18fb5467cb68c7fc3711f59c511"),
    "darwin-amd64": ("ollama-darwin.tgz", "bae29252232b9e1358cf5801a7d65a07442af18fb5467cb68c7fc3711f59c511"),
    "windows-amd64": ("ollama-windows-amd64.zip", "7afa38624fa62ee5d8293422d0ab084c1bb4603134c7f4dafce11a033b57cc19"),
    "windows-arm64": ("ollama-windows-arm64.zip", "32324e770eef0416abb77e42a31a9d79bd752bd9c28582e422666ba24550d56c"),
    "linux-amd64": ("ollama-linux-amd64.tar.zst", "c9490e0f520be21271d969e6703f012268b1d39f8b70dd58854e5bfef7a75bb6"),
    "linux-arm64": ("ollama-linux-arm64.tar.zst", "913d9a28da6da86d551ce4ca531457767bb14d511cbc1d5ca93e9b3b8b9a8666"),
}
MAX_DOWNLOAD_BYTES = 4 * 1024**3
MAX_EXTRACTED_BYTES = 12 * 1024**3
MAX_ARCHIVE_FILES = 25000
CONTEXT_TOKENS = 8192
Emit = Callable[[dict[str, Any]], Awaitable[None]]


class RuntimeSetupError(RuntimeError):
    """A setup failure with a message safe to display in the local UI."""


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{system}-{architecture}"


def _model_name(value: str) -> str:
    if isinstance(value, str) and value.startswith("hf.co/"):
        if len(value) > 512:
            raise RuntimeSetupError("The Hugging Face model reference is too long.")
        repo, separator, tag = value[6:].partition(":")
        try:
            validate_repo_id(repo)
        except HubCatalogError as exc:
            raise RuntimeSetupError(str(exc)) from exc
        if separator:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", tag) or ".." in tag:
                raise RuntimeSetupError("Choose a GGUF quantization or root filename from the repository details.")
            if tag.lower() in {"cloud", "local"} or tag.lower().endswith("-cloud"):
                raise RuntimeSetupError("Cloud model references are not allowed for the local engine.")
        return value
    # Other downloads are restricted to the official Ollama registry.
    if not isinstance(value, str) or len(value) > 160:
        raise RuntimeSetupError("Choose an Ollama registry model with an explicit tag, such as qwen3:4b.")
    pattern = r"(?:[a-z0-9][a-z0-9_.-]*/)?[a-z0-9][a-z0-9_.-]*:[a-zA-Z0-9][a-zA-Z0-9_.-]*"
    if not re.fullmatch(pattern, value) or ".." in value:
        raise RuntimeSetupError("Use a local model tag from the official Ollama registry; URLs and file paths are not supported.")
    if "/" in value and ("." in value.split("/", 1)[0] or value.split("/", 1)[0] == "localhost"):
        raise RuntimeSetupError("Custom registry hosts are not supported. Choose a model from the official Ollama registry.")
    tag = value.rsplit(":", 1)[1].lower()
    if tag in {"cloud", "local"} or tag.endswith("-cloud"):
        raise RuntimeSetupError("Cloud model references are not allowed for the local engine.")
    return value


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _archive_path(root: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not normalized or "\x00" in normalized or normalized.startswith("/") or ".." in parts or any(":" in p for p in parts):
        raise RuntimeSetupError("The runtime archive contains an unsafe path.")
    path = root.joinpath(*parts)
    if not _inside(root, path):
        raise RuntimeSetupError("The runtime archive escapes its installation folder.")
    return path


def _extract_archive(archive: Path, target: Path, canceled: threading.Event | None = None) -> None:
    """Extract regular entries first, then verified in-folder links."""
    total = 0
    entries = 0
    links: list[tuple[Path, str, bool]] = []
    seen: set[Path] = set()

    def check() -> None:
        if canceled is not None and canceled.is_set():
            raise RuntimeSetupError("Runtime setup was canceled.")

    def extract(name: str, size: int, mode: int, source: Any = None, *, directory: bool = False, link: str | None = None, hard: bool = False) -> None:
        nonlocal total, entries
        check()
        entries += 1
        total += size
        if entries > MAX_ARCHIVE_FILES or size < 0 or total > MAX_EXTRACTED_BYTES:
            raise RuntimeSetupError("The runtime archive exceeds the installation size limit.")
        path = _archive_path(target, name)
        if directory:
            path.mkdir(parents=True, exist_ok=True)
            return
        if path in seen or path.exists() or path.is_symlink():
            raise RuntimeSetupError("The runtime archive contains conflicting entries.")
        seen.add(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if link is not None:
            links.append((path, link, hard))
            return
        written = 0
        with path.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                check()
                written += len(chunk)
                if written > size:
                    raise RuntimeSetupError("A runtime archive entry has an invalid length.")
                output.write(chunk)
        if written != size:
            raise RuntimeSetupError("A runtime archive entry is incomplete.")
        if os.name != "nt":
            path.chmod(mode & 0o755)

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode):
                    if item.file_size > 4096:
                        raise RuntimeSetupError("The runtime archive contains an invalid link.")
                    extract(item.filename, item.file_size, mode, link=bundle.read(item).decode("utf-8"))
                elif item.is_dir():
                    extract(item.filename, 0, mode, directory=True)
                elif mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise RuntimeSetupError("The runtime archive contains an unsupported entry.")
                else:
                    with bundle.open(item) as source:
                        extract(item.filename, item.file_size, mode or 0o644, source)
    else:
        with contextlib.ExitStack() as stack:
            source = stack.enter_context(archive.open("rb"))
            if archive.name.endswith(".zst"):
                try:
                    import zstandard
                except ImportError as exc:
                    raise RuntimeSetupError("The app needs its zstandard dependency to install the Linux runtime. Reinstall the app dependencies.") from exc
                source = stack.enter_context(zstandard.ZstdDecompressor().stream_reader(source))
                bundle = stack.enter_context(tarfile.open(fileobj=source, mode="r|"))
            else:
                bundle = stack.enter_context(tarfile.open(fileobj=source, mode="r|gz"))
            for item in bundle:
                if item.isdir():
                    extract(item.name, 0, item.mode, directory=True)
                elif item.issym() or item.islnk():
                    extract(item.name, 0, item.mode, link=item.linkname, hard=item.islnk())
                elif item.isfile():
                    with bundle.extractfile(item) as member:
                        extract(item.name, item.size, item.mode, member)
                else:
                    raise RuntimeSetupError("The runtime archive contains an unsupported entry.")
    for path, link, hard in links:
        check()
        if hard:
            destination = _archive_path(target, link)
            if not destination.is_file() or destination.is_symlink():
                raise RuntimeSetupError("The runtime archive contains an invalid hard link.")
            os.link(destination, path)
        else:
            if "\x00" in link or PurePosixPath(link.replace("\\", "/")).is_absolute() or ":" in link:
                raise RuntimeSetupError("The runtime archive contains an unsafe link.")
            if not _inside(target, path.parent / link):
                raise RuntimeSetupError("The runtime archive link escapes its installation folder.")
            path.symlink_to(link)


def _windows_job(pid: int) -> int:
    """Close-on-exit job ownership prevents orphaned Windows model runners."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeSetupError("Windows could not create an isolated local engine process.")
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
    try:
        if not process or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, process):
            kernel.CloseHandle(handle)
            raise RuntimeSetupError("Windows could not manage the local engine process. No shared process was changed.")
    finally:
        if process:
            kernel.CloseHandle(process)
    return int(handle)


class ManagedRuntime:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.platform = _platform_key()
        self._runtime_dir = self.data_dir / "runtimes" / "ollama" / ("v" + RUNTIME_VERSION) / self.platform
        self._state_path = self.data_dir / "runtime-state.json"
        self._models_dir = self.data_dir / "models"
        self._process: asyncio.subprocess.Process | None = None
        self._port: int | None = None
        self._job: int | None = None
        self._model: str | None = None
        self._digest: str | None = None
        self._verified = False
        self._think: dict[str, Any] = {}
        self._qwen_models: set[str] = set()
        self._error: str | None = None
        self._install_task: asyncio.Task | None = None
        self._installed_models: list[str] = []
        self._read_state()

    @property
    def _binary(self) -> Path:
        if self.platform.startswith("windows-"):
            return self._runtime_dir / "ollama.exe"
        if self.platform.startswith("linux-"):
            return self._runtime_dir / "bin" / "ollama"
        return self._runtime_dir / "ollama"

    @property
    def _base_url(self) -> str:
        if self._port is None:
            raise RuntimeSetupError("Install and start a local model first.")
        return f"http://127.0.0.1:{self._port}"

    def _read_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            if self._state_path.stat().st_size > 256 * 1024:
                raise ValueError
            state = json.loads(self._state_path.read_text("utf-8"))
            if state.get("model"):
                self._model = _model_name(state["model"])
            digest = state.get("model_digest")
            if digest and not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
                raise ValueError
            self._digest = digest
            installed = state.get("installed_models", [])
            if isinstance(installed, list):
                for name in installed[:256]:
                    with contextlib.suppress(RuntimeSetupError):
                        self._installed_models.append(_model_name(name))
        except (OSError, ValueError, TypeError, AttributeError, RuntimeSetupError):
            self._model, self._digest = None, None
            self._error = "The saved local model selection could not be restored. Select a model again."

    def _save_state(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self._state_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump({"version": 1, "runtime_version": RUNTIME_VERSION, "model": self._model, "model_digest": self._digest, "installed_models": self._installed_models[:256]}, output)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self._state_path)

    def _runtime_installed(self) -> bool:
        try:
            receipt = json.loads((self._runtime_dir / "runtime.json").read_text("utf-8"))
            return self._binary.is_file() and receipt == {"version": RUNTIME_VERSION, "asset": ASSETS[self.platform][0], "sha256": ASSETS[self.platform][1]}
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _environment(self) -> dict[str, str]:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("OLLAMA_") and key not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}}
        environment.update({"OLLAMA_HOST": f"127.0.0.1:{self._port}", "OLLAMA_MODELS": str(self._models_dir), "OLLAMA_NO_CLOUD": "1", "OLLAMA_DEBUG": "0", "OLLAMA_DEBUG_LOG_REQUESTS": "0", "OLLAMA_NOHISTORY": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_CONTEXT_LENGTH": str(CONTEXT_TOKENS)})
        environment["OLLAMA_CONTEXT_LENGTH"] = str(max(CONTEXT_TOKENS, 32768))
        return environment

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, trust_env=False, timeout=httpx.Timeout(180, connect=3), follow_redirects=False) as client:
                response = await client.request(method, path, **kwargs)
            if response.status_code >= 300:
                raise RuntimeSetupError(f"The local engine returned HTTP {response.status_code}. Check the selected model and available memory, then retry.")
            if len(response.content) > 4 * 1024**2:
                raise RuntimeSetupError("The local engine returned an unexpectedly large response.")
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeSetupError("The local engine did not return a usable response. Check that it is running and try a smaller model.") from exc

    async def _runtime_ready(self) -> bool:
        if self._process is None or self._process.returncode is not None or self._port is None:
            return False
        try:
            result = await asyncio.wait_for(self._request("GET", "/api/version"), 4)
            return self._process.returncode is None and isinstance(result, dict) and result.get("version") == RUNTIME_VERSION
        except (RuntimeSetupError, asyncio.TimeoutError):
            return False

    async def _start_process(self) -> None:
        if await self._runtime_ready():
            return
        await self._stop_process()
        if not self._runtime_installed():
            raise RuntimeSetupError("Install a local model to set up the managed engine.")
        self._models_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self._port = listener.getsockname()[1]
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        try:
            self._process = await asyncio.create_subprocess_exec(str(self._binary), "serve", cwd=str(self._runtime_dir), env=self._environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            if os.name == "nt":
                self._job = _windows_job(self._process.pid)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self._process.returncode is not None:
                    raise RuntimeSetupError("The local engine could not start. Check OS compatibility and executable permissions.")
                if await self._runtime_ready():
                    return
                await asyncio.sleep(0.2)
            raise RuntimeSetupError("The local engine took too long to start. Retry setup or check this computer's compatibility.")
        except BaseException:
            await self._stop_process()
            raise

    async def _stop_process(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), 8)
            except (OSError, ProcessLookupError, asyncio.TimeoutError):
                if os.name != "nt":
                    with contextlib.suppress(OSError, ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                else:
                    with contextlib.suppress(OSError, ProcessLookupError):
                        process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), 3)
        if self._job is not None:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(self._job)
            self._job = None
        self._port = None

    async def start(self) -> None:
        if not self._runtime_installed():
            return
        try:
            await self._start_process()
            if self._model:
                self._digest = await self._verify_model(self._model, smoke=True)
                self._verified = True
                self._save_state()
            self._error = None
        except (RuntimeSetupError, OSError):
            self._verified = False
            self._error = "The saved local model could not be started. Select a smaller model or retry installation."

    async def status(self) -> dict:
        runtime_ready = await self._runtime_ready()
        if not runtime_ready:
            self._verified = False
        else:
            with contextlib.suppress(RuntimeSetupError):
                listing = await self._request("GET", "/api/tags")
                rows = listing.get("models", []) if isinstance(listing, dict) else []
                if isinstance(rows, list):
                    self._installed_models = [row["name"] for row in rows if isinstance(row, dict) and isinstance(row.get("name"), str) and not row.get("remote_host") and not row.get("remote_model")]
        return {"ready": bool(runtime_ready and self._model and self._verified), "runtime_ready": runtime_ready, "model": self._model, "model_digest": self._digest, "error": self._error, "platform": self.platform, "runtime_version": RUNTIME_VERSION, "installed_models": list(self._installed_models), "installing": self._install_task is not None and not self._install_task.done()}

    async def _download(self, archive: Path, emit: Emit) -> None:
        asset, expected_digest = ASSETS[self.platform]
        location = RELEASE_URL + "/" + asset
        digest = hashlib.sha256()
        received = 0
        allowed_hosts = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(90, connect=20), follow_redirects=False) as client:
                for redirects in range(6):
                    parsed = urlparse(location)
                    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts or parsed.port not in {None, 443} or parsed.username:
                        raise RuntimeSetupError("The engine download redirected outside its approved source.")
                    async with client.stream("GET", location) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = urljoin(location, response.headers.get("location", ""))
                            continue
                        if response.status_code != 200:
                            raise RuntimeSetupError("The official engine download is unavailable. Check the internet connection and retry.")
                        total = int(response.headers.get("content-length", "0"))
                        if total > MAX_DOWNLOAD_BYTES:
                            raise RuntimeSetupError("The engine download exceeds its size limit.")
                        last_update = 0.0
                        with archive.open("wb") as output:
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                received += len(chunk)
                                if received > MAX_DOWNLOAD_BYTES:
                                    raise RuntimeSetupError("The engine download exceeds its size limit.")
                                digest.update(chunk)
                                output.write(chunk)
                                if time.monotonic() - last_update > 0.15:
                                    await emit({"stage": "runtime_download", "message": "Downloading the local engine.", "completed": received, "total": total})
                                    last_update = time.monotonic()
                        if total and received != total:
                            raise RuntimeSetupError("The engine download was incomplete. Retry setup.")
                        break
                else:
                    raise RuntimeSetupError("The engine download redirected too many times.")
            if digest.hexdigest() != expected_digest:
                raise RuntimeSetupError("The engine download failed its SHA256 check. It was not installed; retry setup.")
            await emit({"stage": "runtime_verify", "message": "The engine SHA256 matches the pinned official release.", "completed": received, "total": received})
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise RuntimeSetupError("The local engine could not be downloaded. Check the connection and free disk space, then retry.") from exc

    async def _install_runtime(self, emit: Emit) -> None:
        if self._runtime_installed():
            return
        if self.platform not in ASSETS:
            raise RuntimeSetupError("Managed local models support macOS, Windows and Linux on x86_64 or arm64.")
        if self.platform.startswith("darwin-") and tuple(int(part) for part in platform.mac_ver()[0].split(".")[:1]) < (14,):
            raise RuntimeSetupError("This local engine requires macOS Sonoma 14 or newer.")
        self._runtime_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        working = Path(tempfile.mkdtemp(prefix=".setup-", dir=self._runtime_dir.parent))
        payload = working / "payload"
        payload.mkdir()
        archive = working / ASSETS[self.platform][0]
        cancel = threading.Event()
        extraction: asyncio.Task | None = None
        try:
            await self._download(archive, emit)
            await emit({"stage": "runtime_install", "message": "Installing the verified local engine."})
            extraction = asyncio.create_task(asyncio.to_thread(_extract_archive, archive, payload, cancel))
            await asyncio.shield(extraction)
            relative = self._binary.relative_to(self._runtime_dir)
            binary = payload / relative
            helper = payload / ("llama-server" if self.platform.startswith("darwin-") else "lib/ollama/llama-server" + (".exe" if self.platform.startswith("windows-") else ""))
            if not binary.is_file() or not helper.is_file():
                raise RuntimeSetupError("The official engine archive is missing required runtime files.")
            if os.name != "nt":
                binary.chmod(0o755)
                helper.chmod(0o755)
            (payload / "runtime.json").write_text(json.dumps({"version": RUNTIME_VERSION, "asset": ASSETS[self.platform][0], "sha256": ASSETS[self.platform][1]}), "utf-8")
            if self._runtime_dir.exists():
                await self._stop_process()
                shutil.rmtree(self._runtime_dir)
            payload.replace(self._runtime_dir)
        except asyncio.CancelledError:
            cancel.set()
            if extraction:
                with contextlib.suppress(Exception):
                    await extraction
            raise
        finally:
            shutil.rmtree(working, ignore_errors=True)

    async def _pull(self, model: str, emit: Emit) -> None:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, trust_env=False, timeout=httpx.Timeout(180, connect=3)) as client:
                async with client.stream("POST", "/api/pull", json={"model": model, "stream": True}) as response:
                    if response.status_code != 200:
                        raise RuntimeSetupError("The model download could not start. Check the registry tag and connection.")
                    complete = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if len(line) > 65536:
                            raise RuntimeSetupError("The model download returned an invalid progress message.")
                        event = json.loads(line)
                        if not isinstance(event, dict) or "error" in event:
                            raise RuntimeSetupError("The model download failed. Check the model tag, connection and free disk space.")
                        stage = "model_verify" if "verifying" in event.get("status", "") else "model_download"
                        progress: dict[str, Any] = {"stage": stage, "message": "Verifying model data." if stage == "model_verify" else "Downloading the selected local model."}
                        for key in ("completed", "total"):
                            if isinstance(event.get(key), int) and event[key] >= 0:
                                progress[key] = event[key]
                        if isinstance(event.get("digest"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", event["digest"]):
                            progress["digest"] = event["digest"]
                        await emit(progress)
                        complete = complete or event.get("status") == "success"
                    if not complete:
                        raise RuntimeSetupError("The model download stopped before completion. Retry to resume it.")
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeSetupError("The model download was interrupted. Check the connection and retry to resume it.") from exc

    async def _verify_model(self, model: str, *, smoke: bool) -> str:
        information = await self._request("POST", "/api/show", json={"model": model})
        if not isinstance(information, dict) or information.get("remote_host") or information.get("remote_model"):
            raise RuntimeSetupError("The selected model refers to a remote engine. Choose a fully downloaded local model.")
        if not isinstance(information.get("capabilities"), list) or "completion" not in information["capabilities"]:
            raise RuntimeSetupError("Choose a local text model that supports chat completion.")
        requires = information.get("requires")
        if requires:
            if not isinstance(requires, str) or not re.fullmatch(r"\d+\.\d+\.\d+", requires) or tuple(map(int, requires.split("."))) > tuple(map(int, RUNTIME_VERSION.split("."))):
                raise RuntimeSetupError("This model needs a newer engine than the app's verified release. Choose another model.")
        thinking = information.get("thinking") or {}
        if not isinstance(thinking, dict):
            raise RuntimeSetupError("The local model returned unsupported capability metadata.")
        values = thinking.get("values") or []
        if not isinstance(values, list):
            raise RuntimeSetupError("The local model returned unsupported thinking controls.")
        details = information.get("details") or {}
        family = details.get("family") if isinstance(details, dict) else None
        is_qwen3 = family == "qwen3" or model.split("/")[-1].split(":")[0] == "qwen3"
        if is_qwen3:
            self._qwen_models.add(model)
        else:
            self._qwen_models.discard(model)
        # Qwen3 GGUF manifests can advertise [true] even though the explicit
        # false switch works. Keep curated Qwen3 calls in non-thinking mode.
        can_disable = is_qwen3 or False in values or (not values and "thinking" in information["capabilities"])
        self._think[model] = False if can_disable else None
        listing = await self._request("GET", "/api/tags")
        rows = listing.get("models", []) if isinstance(listing, dict) else []
        if not isinstance(rows, list):
            raise RuntimeSetupError("The local model list could not be read. Retry installation.")
        self._installed_models = [row["name"] for row in rows if isinstance(row, dict) and isinstance(row.get("name"), str) and not row.get("remote_host") and not row.get("remote_model")]
        selected = next((row for row in rows if isinstance(row, dict) and any(isinstance(row.get(key), str) and row[key].casefold() == model.casefold() for key in ("name", "model"))), {})
        digest = selected.get("digest")
        if selected.get("remote_host") or selected.get("remote_model") or not isinstance(digest, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
            raise RuntimeSetupError("The local model digest could not be verified. Retry its installation.")
        if smoke:
            answer = await self._chat_model(model, [{"role": "user", "content": "Reply with the single word OK."}], schema=None, temperature=0, max_tokens=256)
            if not answer.strip():
                raise RuntimeSetupError("The local model did not produce a test answer. Try a smaller model.")
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
            answer = await self._chat_model(model, [{"role": "user", "content": "Return an object with ok set to true."}], schema=schema, temperature=0, max_tokens=256)
            if json.loads(answer) != {"ok": True}:
                raise RuntimeSetupError("This model did not pass the app's structured-response compatibility check. Choose another model.")
        return digest

    async def _hf_download_size(self, model: str) -> int | None:
        if not model.startswith("hf.co/"):
            return None
        repo, separator, tag = model[6:].partition(":")
        try:
            details = await HubCatalog().details(repo)
        except HubCatalogError as exc:
            raise RuntimeSetupError(str(exc)) from exc
        if details.get("gated") is not False or details.get("private") or details.get("offline"):
            raise RuntimeSetupError("Choose a public ungated Hugging Face model with current metadata.")
        variants = [item for item in details["variants"] if item["installable"]]
        if separator:
            matches = [item for item in variants if tag.casefold() in {item["filename"].casefold(), item["quantization"].casefold()}]
        else:
            matches = [item for item in variants if item["quantization"] == "Q4_K_M"] or variants
        if len(matches) != 1:
            raise RuntimeSetupError("Choose one supported GGUF file in the repository details. Split, ambiguous and unsupported model files cannot be downloaded by this app.")
        return matches[0]["size_bytes"]

    async def install(self, model: str, emit: Emit) -> dict:
        model = _model_name(model)
        if self._install_task and not self._install_task.done():
            raise RuntimeSetupError("Another model setup is already running.")
        self._install_task = asyncio.current_task()
        self._error = None
        previous = self._model, self._digest, self._verified
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            planned_bytes = await self._hf_download_size(model)
            if planned_bytes is None:
                planned_bytes = 1_000_000_000
            minimum = int(planned_bytes * 1.1) + 512 * 1024**2
            if not self._runtime_installed():
                minimum += 6 * 1024**3
            if shutil.disk_usage(self.data_dir).free < minimum:
                raise RuntimeSetupError("There is not enough free disk space for this model and its local engine. Free space or choose a smaller model.")
            await self._install_runtime(emit)
            await emit({"stage": "runtime_start", "message": "Starting the private local engine."})
            await self._start_process()
            await self._pull(model, emit)
            await emit({"stage": "model_check", "message": "Checking local chat and structured responses."})
            downloaded_digest = await self._verify_model(model, smoke=True)
            self._model, self._digest, self._verified = previous
            if self._model and self._model.casefold() == model.casefold() and self._digest != downloaded_digest:
                self._digest, self._verified = None, False
            self._save_state()
            await emit({"stage": "downloaded", "message": "The model is downloaded and checked. Choose Use to activate it."})
            return {**await self.status(), "downloaded_model": model}
        except asyncio.CancelledError:
            self._error = "Model setup was canceled. Retry to resume the download."
            self._verified = False
            await self._stop_process()
            raise
        except (RuntimeSetupError, OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
            self._error = str(exc) if isinstance(exc, RuntimeSetupError) else "Local setup failed. Check disk space and retry installation."
            await emit({"stage": "error", "message": self._error})
            raise RuntimeSetupError(self._error) from exc
        finally:
            self._install_task = None

    async def select(self, model: str) -> dict:
        model = _model_name(model)
        await self._start_process()
        digest = await self._verify_model(model, smoke=True)
        self._model, self._digest, self._verified, self._error = model, digest, True, None
        self._save_state()
        return await self.status()

    async def remove(self, model: str) -> None:
        model = _model_name(model)
        await self._start_process()
        await self._request("DELETE", "/api/delete", json={"model": model})
        self._installed_models = [name for name in self._installed_models if name.casefold() != model.casefold()]
        if self._model and model.casefold() == self._model.casefold():
            self._model, self._digest, self._verified, self._error = None, None, False, None
        self._save_state()

    async def _chat_model(self, model: str, messages: list[dict], *, schema: dict | None, temperature: float, max_tokens: int) -> str:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise RuntimeSetupError("Provide between 1 and 100 text conversation turns.")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 4096:
            raise RuntimeSetupError("The local output limit must be between 1 and 4096 tokens.")
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise RuntimeSetupError("The local temperature must be between 0 and 2.")
        prepared = []
        for turn in messages:
            if not isinstance(turn, dict) or turn.get("role") not in {"system", "user", "assistant"} or not isinstance(turn.get("content"), str):
                raise RuntimeSetupError("Local chat supports text system, user and assistant turns.")
            prepared.append({"role": turn["role"], "content": turn["content"]})
        if schema is not None:
            if not isinstance(schema, dict):
                raise RuntimeSetupError("A structured response requires a JSON object schema.")
            schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            if len(schema_text.encode("utf-8")) > 16384:
                raise RuntimeSetupError("The structured response schema is too large for the local model.")
            prepared.insert(0, {"role": "system", "content": "Return only JSON matching this schema: " + schema_text})
        # UTF-8 bytes plus turn/template reserves deliberately overestimate tokens.
        upper_bound = sum(len(turn["content"].encode("utf-8")) + 64 for turn in prepared) + max_tokens + 512
        if upper_bound > CONTEXT_TOKENS:
            raise RuntimeSetupError("This conversation exceeds the local context budget. Start a new conversation or shorten the input; history was not truncated.")
        payload: dict[str, Any] = {"model": model, "messages": prepared, "stream": False, "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": CONTEXT_TOKENS}}
        if self._think.get(model) is False:
            payload["think"] = False
        if schema is not None:
            payload["format"] = schema
        response = await self._request("POST", "/api/chat", json=payload)
        if not isinstance(response, dict) or response.get("remote_host") or response.get("remote_model"):
            raise RuntimeSetupError("The local engine returned an unexpected remote-model response.")
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip() or response.get("done") is not True:
            raise RuntimeSetupError("The local model returned no complete answer. Try a smaller model or shorter input.")
        if response.get("done_reason") == "length":
            raise RuntimeSetupError("The local answer reached its output limit. Shorten the request or increase the output limit.")
        # Some Qwen3 templates place a reasoning prefix in content even when
        # think=false. Only the final text after its closing delimiter is an answer.
        is_qwen3 = model in self._qwen_models or model.split("/")[-1].split(":")[0] == "qwen3"
        if content.lstrip().startswith("<think>"):
            if "</think>" not in content:
                raise RuntimeSetupError("The local model returned an unfinished reasoning block. Retry with a shorter request.")
            content = content.split("</think>", 1)[1].strip()
        elif is_qwen3:
            delimiter = re.search(r"(?m)^[ \t]*</think>[ \t]*(?:\r?\n|$)", content)
            if delimiter:
                content = content[delimiter.end():].strip()
        if not content.strip():
            raise RuntimeSetupError("The local model returned reasoning without a final answer. Retry with a shorter request.")
        if schema is not None:
            try:
                json.loads(content)
            except ValueError as exc:
                raise RuntimeSetupError("The local model did not return valid JSON. Choose another model or retry.") from exc
        return content

    async def chat(self, messages: list[dict], *, schema: dict | None = None, temperature: float = 0, max_tokens: int = 1024) -> str:
        if not self._model or not self._verified or not await self._runtime_ready():
            raise RuntimeSetupError("Install and select a local model before running a prompt.")
        return await self._chat_model(self._model, messages, schema=schema, temperature=temperature, max_tokens=max_tokens)

    async def stop(self) -> None:
        task = self._install_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeSetupError):
                await task
        await self._stop_process()
        self._verified = False
