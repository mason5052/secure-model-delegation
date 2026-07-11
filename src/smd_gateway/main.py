from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Optional, Union

from .audit import write_audit_log
from .delegation import send_to_simulated_endpoint
from .egress import EgressGuardViolation, EgressValidation, enforce_egress_payload
from .egress_sanitizer import sanitize_egress_with_map
from .evidence import detect_sensitive_spans
from .leakage import evaluate_leakage
from .normalizer import assemble_request
from .policy import DELEGATION_ROUTES, decide_policy
from .policy_config import load_policy_config
from .request_model import GatewayResult, NormalizedRequest, RequestBundle


def process_request(
    bundle: RequestBundle,
    leakage_oracle: Optional[Any] = None,
    run_dir: Union[str, Path] = "runs",
    policy_path: Optional[Union[str, Path]] = None,
    evidence_override: Optional[list[Any]] = None,
    use_utility: bool = True,
) -> GatewayResult:
    run_path = Path(run_dir)
    policy = load_policy_config(policy_path)
    request = assemble_request(bundle)
    spans = (
        evidence_override
        if evidence_override is not None
        else detect_sensitive_spans(request, policy=policy)
    )
    decision = decide_policy(request, spans, policy=policy, use_utility=use_utility)
    evaluation_oracle = _effective_oracle(leakage_oracle, spans)

    delegated_payload: Optional[str] = None
    external_ref: Optional[str] = None
    egress_validation: Optional[EgressValidation] = None
    wire_metadata: dict[str, Any] = {}
    placeholder_count = 0
    if decision.route in DELEGATION_ROUTES:
        delegation_request, delegation_spans = _delegation_view(request, policy)
        sanitization = sanitize_egress_with_map(
            delegation_request.text,
            delegation_spans,
            route=decision.route,
            policy=policy,
        )
        delegated_payload = sanitization.text
        placeholder_count = len(sanitization.placeholder_to_original)
        runtime_oracle = _effective_oracle(None, delegation_spans)
        try:
            egress_validation = enforce_egress_payload(delegated_payload, runtime_oracle)
        except EgressGuardViolation as exc:
            egress_validation = exc.validation
            blocked_route = decision.route
            decision = replace(
                decision,
                route="local_summary",
                hard_action="summarize_locally",
                utility_label="partial",
                reasons=[
                    *decision.reasons,
                    "Egress verification found protected runtime evidence after transformation.",
                ],
                rule_ids=[*decision.rule_ids, "egress_guard_fail_closed"],
                advisory_route=None,
                candidate_routes=sorted(
                    (set(decision.candidate_routes) - {blocked_route})
                    | {"local_summary"}
                ),
                eliminated_routes=[
                    item
                    for item in decision.eliminated_routes
                    if item.get("route") != "local_summary"
                ]
                + [{"route": blocked_route, "reason": "egress_guard_blocked"}],
                conflict_rule_id="egress_guard_fail_closed",
                conflict_priority=130,
                transformation_type="local_summary",
                utility_assessment={
                    **decision.utility_assessment,
                    "label": "partial",
                    "egress_guard": "blocked",
                },
                decision_trace=[
                    *decision.decision_trace,
                    "egress_guard:blocked_to_local_summary",
                ],
            )
            delegated_payload = None
        else:
            external_ref, wire_metadata = send_to_simulated_endpoint(
                run_path,
                case_id=request.case_id,
                target_profile=decision.target_profile or "approved_external_ai",
                transport=decision.transport,
                payload=delegated_payload,
                egress_validation=egress_validation.audit_metadata(),
            )

    audit_ref = write_audit_log(
        run_path,
        request,
        spans,
        decision,
        external_ref,
        egress_validation=(
            egress_validation.audit_metadata()
            if egress_validation is not None
            else {"status": "not_applicable"}
        ),
        wire_metadata=wire_metadata,
        placeholder_count=placeholder_count,
    )
    leakage = evaluate_leakage(delegated_payload or "", evaluation_oracle)
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
        route_utility_scores=decision.route_utility_scores,
        decision_trace=decision.decision_trace,
        direct_leakage_found=leakage["direct"],
        canonicalized_leakage_found=leakage["canonicalized"],
        structural_code_leakage_found=leakage["structural_code"],
    )


def _effective_oracle(leakage_oracle: Optional[Any], spans: list[Any]) -> Any:
    if leakage_oracle is not None:
        return leakage_oracle
    return {
        "must_not_contain": [
            span.text
            for span in spans
            if span.text and span.policy_action != "allow"
        ]
    }


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
