from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:6727"


def main() -> None:
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run_web.py")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server()
        health = _get_json("/api/health")
        examples = _get_json("/api/examples")
        result = _post_json(
            "/api/process",
            {
                "case_id": "WEB_SMOKE_API_KEY",
                "user_prompt": "Debug this 401 API error: SERVICE_KEY=synthetic-service-key-123456 returns unauthorized.",
                "target_profile": "external_ai",
                "transport": "simulated_external_endpoint",
            },
        )

        raw_key = "synthetic-service-key-123456"
        delegated_payload = result.get("delegated_payload") or ""
        checks = {
            "health": health == {"status": "ok"},
            "examples_count": len(examples),
            "route": result.get("route"),
            "raw_key_leaked": raw_key in delegated_payload,
            "leakage_found": result.get("leakage_found"),
        }
        print(json.dumps(checks, indent=2, ensure_ascii=True))

        if not checks["health"]:
            raise SystemExit("health check failed")
        if checks["examples_count"] < 5:
            raise SystemExit("examples check failed")
        if checks["raw_key_leaked"]:
            raise SystemExit("raw key leaked in delegated payload")
        if checks["leakage_found"]:
            raise SystemExit("leakage check failed")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_for_server() -> None:
    deadline = time.time() + 10
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            _get_json("/api/health")
            return
        except Exception as exc:  # noqa: BLE001 - smoke test reports final error.
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"server did not start: {last_error}")


def _get_json(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


if __name__ == "__main__":
    main()
