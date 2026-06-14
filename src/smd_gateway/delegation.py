from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def send_to_simulated_endpoint(
    run_dir: Path,
    case_id: str,
    target_profile: str,
    transport: str,
    payload: str,
) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "simulated_external_payloads.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "target_profile": target_profile,
        "transport": transport,
        "payload": payload,
    }
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(out_path)
