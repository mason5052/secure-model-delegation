from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn
from platformdirs import user_data_path


def main():
    parser = argparse.ArgumentParser(description="Local-first Secure Model Delegation")
    parser.add_argument("command", choices=["serve"], nargs="?", default="serve")
    parser.add_argument("--port", type=int, default=6728)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    data_dir = args.data_dir or user_data_path("SecureModelDelegation", appauthor=False)
    try:
        with socket.socket() as probe:
            probe.settimeout(1)
            occupied = probe.connect_ex(("127.0.0.1", args.port)) == 0
    except OSError:
        parser.error("Cannot access the local port. Check local network permissions.")
    if occupied:
        parser.error("This port is already in use. Restart with --port and another number.")
    from .app import create_app
    app = create_app(data_dir.resolve())
    url = f"http://127.0.0.1:{args.port}"
    print(f"Secure Model Delegation: {url}")
    print(f"Local application data: {data_dir}")
    print("Choose a model in the browser to install the required local AI. External API connections are optional.")
    if not args.no_browser:
        def open_when_ready():
            for _ in range(120):
                try:
                    with urllib.request.urlopen(url, timeout=1):
                        webbrowser.open(url)
                    return
                except (urllib.error.URLError, OSError):
                    time.sleep(1)
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
