from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from .audit import write_audit_log
from .delegation import send_to_simulated_endpoint
from .evidence import detect_sensitive_spans
from .leakage import evaluate_leakage
from .normalizer import assemble_request
from .policy import DELEGATION_ROUTES, decide_policy
from .policy_config import load_policy_config
from .request_model import GatewayResult, NormalizedRequest, RequestBundle
from .sanitizer import sanitize_text


def process_request(
    bundle: RequestBundle,
    leakage_oracle: Optional[Any] = None,
    run_dir: Union[str, Path] = "runs",
    policy_path: Optional[Union[str, Path]] = None,
) -> GatewayResult:
    run_path = Path(run_dir)
    policy = load_policy_config(policy_path)
    request = assemble_request(bundle)
    spans = detect_sensitive_spans(request, policy=policy)
    decision = decide_policy(request, spans, policy=policy)

    delegated_payload: Optional[str] = None
    external_ref: Optional[str] = None
    if decision.route in DELEGATION_ROUTES:
        delegation_request, delegation_spans = _delegation_view(request, policy)
        delegated_payload = sanitize_text(
            delegation_request.text,
            delegation_spans,
            route=decision.route,
            policy=policy,
        )
        external_ref = send_to_simulated_endpoint(
            run_path,
            case_id=request.case_id,
            target_profile=decision.target_profile or "approved_external_ai",
            transport=decision.transport,
            payload=delegated_payload,
        )

    audit_ref = write_audit_log(run_path, request, spans, decision, external_ref)
    effective_oracle = leakage_oracle
    if effective_oracle is None:
        effective_oracle = {"must_not_contain": [span.text for span in spans if span.text]}
    leakage = evaluate_leakage(delegated_payload or "", effective_oracle)
    all_leakage = sorted(set(leakage["direct"] + leakage["canonicalized"] + leakage["structural_code"]))

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
        leakage_found=all_leakage,
        audit_ref=audit_ref,
        external_ref=external_ref,
        external_endpoint_payload_ref=external_ref,
        candidate_routes=decision.candidate_routes,
        eliminated_routes=decision.eliminated_routes,
        span_actions=decision.span_actions,
        conflict_rule_id=decision.conflict_rule_id,
        conflict_priority=decision.conflict_priority,
        transformation_type=decision.transformation_type,
        policy_version=decision.policy_version,
        utility_assessment=decision.utility_assessment,
        decision_trace=decision.decision_trace,
        direct_leakage_found=leakage["direct"],
        canonicalized_leakage_found=leakage["canonicalized"],
        structural_code_leakage_found=leakage["structural_code"],
    )


def _delegation_view(request: NormalizedRequest, policy: Any) -> tuple[NormalizedRequest, list[Any]]:
    if not request.conversation_turns:
        return request, detect_sensitive_spans(request, policy=policy, include_cross_turn=False)
    current = NormalizedRequest(
        case_id=request.case_id,
        target_profile=request.target_profile,
        transport=request.transport,
        text=request.current_text,
        current_text=request.current_text,
        sources=["user_prompt"],
        conversation_turns=[],
        metadata={},
    )
    return current, detect_sensitive_spans(current, policy=policy, include_cross_turn=False)


def _span_for_ui(span: Any) -> dict[str, Any]:
    return {
        "label": span.label,
        "detector": span.detector,
        "provider_group": span.provider_group,
        "severity": span.severity,
        "action": span.policy_action,
        "start": span.start,
        "end": span.end,
        "preview": _safe_preview(span),
    }


def _safe_preview(span: Any) -> str:
    if span.start == span.end and span.detector == "cross_turn_secret_reconstruction":
        return f"<{span.label}:split across turns>"
    if len(span.text) <= 10:
        return f"<{span.label}:{len(span.text)} chars>"
    if span.label in {
        "api_key",
        "auth_token",
        "config_secret",
        "source_code",
        "proprietary_code",
        "incident_detail",
        "system_prompt",
        "prompt_injection",
    }:
        return f"<{span.label}:{len(span.text)} chars>"
    return f"{span.text[:4]}...{span.text[-3:]} ({len(span.text)} chars)"
