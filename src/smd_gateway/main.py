from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from .audit import write_audit_log
from .delegation import send_to_simulated_endpoint
from .evidence import detect_sensitive_spans
from .leakage import find_direct_leakage
from .normalizer import assemble_request
from .policy import DELEGATION_ROUTES, decide_policy
from .request_model import GatewayResult, RequestBundle
from .sanitizer import sanitize_text


def process_request(
    bundle: RequestBundle,
    leakage_oracle: Optional[Any] = None,
    run_dir: Union[str, Path] = "runs",
) -> GatewayResult:
    run_path = Path(run_dir)
    request = assemble_request(bundle)
    spans = detect_sensitive_spans(request)
    decision = decide_policy(request, spans)

    delegated_payload: Optional[str] = None
    external_ref: Optional[str] = None

    if decision.route in DELEGATION_ROUTES:
        delegated_payload = sanitize_text(request.text, spans, route=decision.route)
        external_ref = send_to_simulated_endpoint(
            run_path,
            case_id=request.case_id,
            target_profile=decision.target_profile or "external_ai",
            transport=decision.transport,
            payload=delegated_payload,
        )

    audit_ref = write_audit_log(run_path, request, spans, decision, external_ref)
    effective_oracle = leakage_oracle
    if effective_oracle is None:
        effective_oracle = {"must_not_contain": [span.text for span in spans]}
    leakage_found = find_direct_leakage(delegated_payload or "", effective_oracle)

    return GatewayResult(
        case_id=request.case_id,
        route=decision.route,
        hard_action=decision.hard_action,
        utility_label=decision.utility_label,
        target_profile=decision.target_profile,
        transport=decision.transport,
        detected_labels=sorted({span.label for span in spans}),
        detected_spans=[_span_for_ui(span) for span in spans],
        decision_reasons=decision.reasons,
        rule_ids=decision.rule_ids,
        advisory_route=decision.advisory_route,
        delegated_payload=delegated_payload,
        sanitized_or_delegated_payload=delegated_payload,
        leakage_found=leakage_found,
        audit_ref=audit_ref,
        external_ref=external_ref,
        external_endpoint_payload_ref=external_ref,
    )


def _span_for_ui(span: Any) -> dict[str, Any]:
    return {
        "label": span.label,
        "detector": span.detector,
        "severity": span.severity,
        "action": span.policy_action,
        "start": span.start,
        "end": span.end,
        "preview": _safe_preview(span),
    }


def _safe_preview(span: Any) -> str:
    high_risk = {
        "api_key",
        "auth_token",
        "config_secret",
        "source_code",
        "proprietary_code",
        "incident_detail",
        "system_prompt",
        "prompt_injection",
    }
    if span.label in high_risk:
        return f"<{span.label}:{len(span.text)} chars>"
    if len(span.text) <= 10:
        return f"<{span.label}:{len(span.text)} chars>"
    return f"{span.text[:4]}...{span.text[-3:]} ({len(span.text)} chars)"
