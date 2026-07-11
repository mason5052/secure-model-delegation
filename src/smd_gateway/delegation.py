from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def send_to_simulated_endpoint(
    run_dir: Path,
    case_id: str,
    target_profile: str,
    transport: str,
    payload: str,
    egress_validation: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "simulated_external_payloads.jsonl"
    wire_body = {
        "case_id": case_id,
        "target_profile": target_profile,
        "transport": transport,
        "payload": payload,
    }
    wire_bytes = json.dumps(
        wire_body,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    wire_metadata = {
        "wire_body_sha256": hashlib.sha256(wire_bytes).hexdigest(),
        "wire_body_bytes": len(wire_bytes),
        "egress_guard_status": egress_validation["status"],
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **wire_body,
        **wire_metadata,
    }
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(out_path), wire_metadata
