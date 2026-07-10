from __future__ import annotations

from collections import Counter
from typing import Optional

from .leakage import evaluate_leakage
from .policy_config import ConflictRule, PolicyConfig, load_policy_config
from .request_model import NormalizedRequest, PolicyDecision, SensitiveSpan
from .router import assess_utility, score_allowed_routes, select_highest_utility_route
from .sanitizer import sanitize_text, transformation_type_for_route


DELEGATION_ROUTES = {
    "delegate_sanitized_to_external_ai",
    "delegate_pseudocode_to_external_ai",
}
SAFE_LOCAL_ROUTES = {
    "local_process",
    "deny_request",
    "ask_clarification",
    "local_summary",
}
HIGH_RISK_LABELS = {
    "api_key",
    "auth_token",
    "config_secret",
    "source_code",
    "proprietary_code",
    "incident_detail",
    "system_prompt",
}


def decide_policy(
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    policy: Optional[PolicyConfig] = None,
    use_utility: bool = True,
) -> PolicyDecision:
    policy = policy or load_policy_config()
    canonical_target = policy.canonical_target(request.target_profile)
    labels = {span.label for span in spans}
    flags = _request_flags(request)
    reasons = _reasons(spans)
    trace = [
        "evidence_collected",
        f"policy_loaded:{policy.version}",
        f"target_resolved:{canonical_target}",
    ]

    candidates, eliminated = _allowed_routes(policy, labels, canonical_target)
    trace.append("allowed_routes_calculated")
    span_actions = _span_actions(spans)

    conflict = _first_matching_conflict(
        policy,
        labels=labels,
        request_flags=flags,
        target_profile=canonical_target,
    )
    if conflict and conflict.force_route:
        selected = conflict.force_route if conflict.force_route in candidates else _safe_fallback(candidates)
        for route in sorted(candidates - {selected}):
            eliminated.append({"route": route, "reason": f"conflict_rule:{conflict.rule_id}"})
        candidates = {selected}
        trace.append(f"conflict_resolved:{conflict.rule_id}:{conflict.priority}")
        return _finalize(
            request=request,
            policy=policy,
            route=selected,
            canonical_target=canonical_target,
            spans=spans,
            candidates=candidates,
            eliminated=eliminated,
            span_actions=span_actions,
            reasons=reasons + ([conflict.effect] if conflict.effect else []),
            rule_ids=["hard_policy_first", conflict.rule_id],
            conflict=conflict,
            trace=trace,
            route_utility_scores={},
        )

    selected, route_scores, candidates, newly_eliminated = _select_policy_constrained_route(
        request,
        spans,
        policy,
        candidates,
        use_utility=use_utility,
    )
    eliminated.extend(newly_eliminated)
    trace.extend(["transformed_payload_checked", "all_allowed_routes_scored", "final_route_selected"])
    rule_id = (
        "policy_constrained_utility_argmax"
        if use_utility
        else "hard_policy_preference_without_utility"
    )
    return _finalize(
        request=request,
        policy=policy,
        route=selected,
        canonical_target=canonical_target,
        spans=spans,
        candidates=candidates,
        eliminated=eliminated,
        span_actions=span_actions,
        reasons=reasons + (["no sensitive spans detected"] if not spans else []),
        rule_ids=["hard_policy_first", rule_id],
        conflict=None,
        trace=trace,
        route_utility_scores=route_scores,
    )


def _allowed_routes(
    policy: PolicyConfig,
    labels: set[str],
    canonical_target: str,
) -> tuple[set[str], list[dict[str, str]]]:
    candidates = set(policy.route_labels)
    for label in sorted(labels):
        class_policy = policy.class_policy(label)
        candidates &= set(class_policy.allowed_routes) | SAFE_LOCAL_ROUTES
        target_directive = class_policy.target_policy.get(canonical_target)
        if target_directive:
            candidates &= _routes_for_target_directive(target_directive)
    if not labels & {"source_code", "proprietary_code"}:
        candidates.discard("delegate_pseudocode_to_external_ai")
    if canonical_target == "local_private":
        candidates &= SAFE_LOCAL_ROUTES
    if not candidates:
        candidates = {"deny_request"}
    eliminated = [
        {"route": route, "reason": "not_allowed_by_class_or_target_policy"}
        for route in sorted(set(policy.route_labels) - candidates)
    ]
    return candidates, eliminated


def _routes_for_target_directive(directive: str) -> set[str]:
    mappings = {
        "allow_raw_local_processing": {"local_process"},
        "delegate_pseudocode_only": {
            "local_process",
            "local_summary",
            "ask_clarification",
            "deny_request",
            "delegate_pseudocode_to_external_ai",
        },
        "local_summary_only": {"local_summary", "deny_request"},
    }
    try:
        return mappings[directive]
    except KeyError as exc:
        raise ValueError(f"Unknown target policy directive: {directive}") from exc


def _request_flags(request: NormalizedRequest) -> set[str]:
    flags: set[str] = set()
    lowered = request.text.lower()
    if "local only" in lowered or "handle this locally" in lowered or "do not delegate" in lowered:
        flags.add("explicit_local_only")
    if request.metadata.get("cross_turn_sensitive"):
        flags.add("cross_turn_sensitive")
    return flags


def _first_matching_conflict(
    policy: PolicyConfig,
    labels: set[str],
    request_flags: set[str],
    target_profile: str,
) -> Optional[ConflictRule]:
    for rule in policy.conflict_rules:
        if not rule.force_route:
            continue
        if rule.target_profiles and target_profile not in rule.target_profiles:
            continue
        if rule.when_all_labels and not rule.when_all_labels <= labels:
            continue
        if rule.when_any_labels and not rule.when_any_labels & labels:
            continue
        if rule.when_any_companion_labels and not rule.when_any_companion_labels & labels:
            continue
        if rule.when_request_flags and not rule.when_request_flags <= request_flags:
            continue
        return rule
    return None


def _select_policy_constrained_route(
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    policy: PolicyConfig,
    candidates: set[str],
    use_utility: bool,
) -> tuple[str, dict[str, dict[str, object]], set[str], list[dict[str, str]]]:
    safe_candidates = set(candidates)
    eliminated: list[dict[str, str]] = []
    route_payloads: dict[str, str] = {}
    for route in sorted(candidates):
        if route not in DELEGATION_ROUTES:
            route_payloads[route] = request.text
            continue
        payload = sanitize_text(request.text, spans, route=route, policy=policy)
        leakage = evaluate_leakage(
            payload,
            {"must_not_contain": [span.text for span in spans if span.text]},
        )
        if any(leakage.values()):
            safe_candidates.discard(route)
            eliminated.append({"route": route, "reason": "transformed_payload_failed_safety_check"})
            continue
        route_payloads[route] = payload

    if not safe_candidates:
        safe_candidates = {"deny_request"}
        route_payloads["deny_request"] = request.text
    route_scores = score_allowed_routes(
        request,
        spans,
        safe_candidates,
        route_payloads,
        policy,
    )
    if use_utility:
        selected = select_highest_utility_route(route_scores, policy)
    else:
        selected = max(
            safe_candidates,
            key=lambda route: (policy.route_preference[route], route),
        )
    return selected, route_scores, safe_candidates, eliminated


def _safe_fallback(candidates: set[str]) -> str:
    for route in ("local_summary", "local_process", "ask_clarification", "deny_request"):
        if route in candidates:
            return route
    return "deny_request"


def _finalize(
    request: NormalizedRequest,
    policy: PolicyConfig,
    route: str,
    canonical_target: str,
    spans: list[SensitiveSpan],
    candidates: set[str],
    eliminated: list[dict[str, str]],
    span_actions: list[dict[str, object]],
    reasons: list[str],
    rule_ids: list[str],
    conflict: Optional[ConflictRule],
    trace: list[str],
    route_utility_scores: dict[str, dict[str, object]],
) -> PolicyDecision:
    assessment_text = request.text
    if route in DELEGATION_ROUTES:
        assessment_text = sanitize_text(request.text, spans, route=route, policy=policy)
    assessment = assess_utility(assessment_text)
    if route in route_utility_scores:
        assessment = {
            **assessment,
            "decision_score": route_utility_scores[route]["score"],
            "route_components": route_utility_scores[route],
        }
    hard_action = {
        "deny_request": "deny_span",
        "local_summary": "summarize_locally",
        "delegate_pseudocode_to_external_ai": "summarize_locally",
        "delegate_sanitized_to_external_ai": "transform",
    }.get(route, "allow")
    if route == "ask_clarification":
        assessment = {**assessment, "label": "insufficient", "score": 0.1}
    elif route == "local_summary" and assessment["label"] == "sufficient":
        assessment = {**assessment, "label": "partial", "score": 0.55}
    target = canonical_target if route in DELEGATION_ROUTES else None
    transport = request.transport if route in DELEGATION_ROUTES else "none"
    return PolicyDecision(
        route=route,
        target_profile=target,
        transport=transport,
        hard_action=hard_action,
        utility_label=str(assessment["label"]),
        reasons=reasons,
        rule_ids=rule_ids,
        advisory_route=route if route in DELEGATION_ROUTES else None,
        candidate_routes=sorted(candidates),
        eliminated_routes=eliminated,
        span_actions=span_actions,
        conflict_rule_id=None if conflict is None else conflict.rule_id,
        conflict_priority=None if conflict is None else conflict.priority,
        transformation_type=transformation_type_for_route(route),
        policy_version=policy.version,
        utility_assessment=assessment,
        route_utility_scores=route_utility_scores,
        decision_trace=trace,
    )


def _span_actions(spans: list[SensitiveSpan]) -> list[dict[str, object]]:
    return [
        {
            "span_id": f"span_{index}",
            "label": span.label,
            "action": span.policy_action,
            "severity": span.severity,
            "detector": span.detector,
        }
        for index, span in enumerate(spans, start=1)
    ]


def _reasons(spans: list[SensitiveSpan]) -> list[str]:
    counts = Counter(span.label for span in spans)
    return [f"{label}:{count}" for label, count in sorted(counts.items())]
