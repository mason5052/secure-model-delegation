"""Private desktop entry point; the ordinary browser CLI remains available."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn
from platformdirs import user_data_path


def seed_bundled_runtime(data_dir: Path, bundle: Path | None) -> bool:
    """Copy only the public engine, never a model or a previous user's state."""
    if bundle is None:
        return False
    from .runtime import ASSETS, RUNTIME_VERSION, _platform_key
    platform_key = _platform_key()
    expected = {"version": RUNTIME_VERSION, "asset": ASSETS[platform_key][0], "sha256": ASSETS[platform_key][1]}
    bundle = bundle.resolve(strict=True)
    if json.loads((bundle / "runtime.json").read_text("utf-8")) != expected:
        raise ValueError("The bundled engine receipt does not match this application.")
    if not (bundle / "ollama").is_file() or not (bundle / "llama-server").is_file():
        raise ValueError("The bundled engine is incomplete.")
    for entry in bundle.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(bundle):
            raise ValueError("The bundled engine contains an external link.")
    destination = data_dir / "runtimes" / "ollama" / ("v" + RUNTIME_VERSION) / platform_key
    if destination.exists():
        return False
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".desktop-engine-", dir=destination.parent))
    try:
        shutil.copytree(bundle, staging, dirs_exist_ok=True, symlinks=True)
        staging.chmod(0o700)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return True


def acquire_data_lock(data_dir: Path):
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    path = data_dir / "desktop.lock"
    handle = path.open("a+")
    path.chmod(0o600)
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(" ")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise RuntimeError("Another desktop instance is using this application data folder.") from None
    return handle


async def serve(data_dir: Path, parent_pid: int | None = None) -> None:
    from .app import create_app
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    os.environ["SMD_DESKTOP_PORT"] = str(port)
    app = create_app(data_dir)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                         access_log=False, log_level="error",
                                         timeout_graceful_shutdown=20))
    loop = asyncio.get_running_loop()

    def control_input() -> None:
        for line in sys.stdin:
            try:
                if json.loads(line) == {"command": "shutdown"}:
                    loop.call_soon_threadsafe(setattr, server, "should_exit", True)
                    return
            except (ValueError, RuntimeError):
                continue
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    threading.Thread(target=control_input, daemon=True).start()

    async def monitor() -> None:
        announced = False
        while not server.should_exit:
            if server.started and not announced:
                runtime = app.state.runtime
                processes = [getattr(getattr(runtime, "ollama", runtime), "_process", None),
                             getattr(getattr(runtime, "mlx", None), "process", None)]
                children = [process.pid for process in processes if process is not None and process.returncode is None]
                print(json.dumps({"event": "ready", "host": "127.0.0.1", "port": port,
                                  "pid": os.getpid(), "child_pids": children}), flush=True)
                announced = True
            if parent_pid:
                try:
                    os.kill(parent_pid, 0)
                except ProcessLookupError:
                    server.should_exit = True
                except PermissionError:
                    pass
            await asyncio.sleep(0.2)

    monitor_task = asyncio.create_task(monitor())
    try:
        await server.serve(sockets=[listener])
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        listener.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="aethon desktop service")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args()
    current = user_data_path("aethon", appauthor=False)
    legacy = user_data_path("SecureModelDelegation", appauthor=False)
    current_has_data = any((current / name).exists() for name in ("application.sqlite3", "runtime-state.json"))
    default = legacy if legacy.exists() and not current_has_data else current
    data_dir = (args.data_dir or default).resolve()
    with acquire_data_lock(data_dir):
        bundle = os.environ.get("SMD_BUNDLED_OLLAMA_DIR")
        seed_bundled_runtime(data_dir, Path(bundle) if bundle else None)
        asyncio.run(serve(data_dir, args.parent_pid))


if __name__ == "__main__":
    main()
