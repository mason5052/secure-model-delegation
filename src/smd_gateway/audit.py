from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .request_model import NormalizedRequest, PolicyDecision, SensitiveSpan


def write_audit_log(
    run_dir: Path,
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    decision: PolicyDecision,
    external_ref: Optional[str],
    egress_validation: Optional[dict[str, Any]] = None,
    wire_metadata: Optional[dict[str, Any]] = None,
    placeholder_count: int = 0,
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
        "candidate_routes": decision.candidate_routes,
        "eliminated_routes": decision.eliminated_routes,
        "span_actions": decision.span_actions,
        "conflict_rule_id": decision.conflict_rule_id,
        "conflict_priority": decision.conflict_priority,
        "transformation_type": decision.transformation_type,
        "policy_version": decision.policy_version,
        "utility_assessment": decision.utility_assessment,
        "route_utility_scores": decision.route_utility_scores,
        "decision_trace": decision.decision_trace,
        "reasons": decision.reasons,
        "external_ref": external_ref,
        "egress_validation": egress_validation or {"status": "not_applicable"},
        "wire_metadata": wire_metadata or {},
        "placeholder_count": placeholder_count,
        "raw_input_stored": False,
    }
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(out_path)
