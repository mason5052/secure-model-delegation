from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .request_model import NormalizedRequest, PolicyDecision, SensitiveSpan


def write_audit_log(
    run_dir: Path,
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    decision: PolicyDecision,
    external_ref: Optional[str],
) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "audit.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": request.case_id,
        "request_sha256": hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
        "detected_labels": sorted({span.label for span in spans}),
        "span_count": len(spans),
        "route": decision.route,
        "transport": decision.transport,
        "hard_action": decision.hard_action,
        "utility_label": decision.utility_label,
        "target_profile": decision.target_profile,
        "rule_ids": decision.rule_ids,
        "advisory_route": decision.advisory_route,
        "reasons": decision.reasons,
        "external_ref": external_ref,
        "raw_input_stored": False,
    }
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(out_path)
