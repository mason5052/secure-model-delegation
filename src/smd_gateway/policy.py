from __future__ import annotations

from collections import Counter
from typing import Optional

from .request_model import NormalizedRequest, PolicyDecision, SensitiveSpan
from .router import advisory_route, estimate_utility
from .sanitizer import sanitize_text


DELEGATION_ROUTES = {
    "delegate_sanitized_to_external_ai",
    "delegate_pseudocode_to_external_ai",
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

SECRET_LABELS = {"api_key", "auth_token", "config_secret"}
CODE_LABELS = {"source_code", "proprietary_code"}
INFRA_LABELS = {"internal_hostname", "private_ip", "internal_infrastructure"}
PII_LABELS = {"pii_name", "pii_email", "pii_phone"}


def decide_policy(request: NormalizedRequest, spans: list[SensitiveSpan]) -> PolicyDecision:
    labels = {span.label for span in spans}
    reasons = _reasons(spans)
    rule_ids: list[str] = ["hard_policy_first"]
    if _requested_local_handling(request.text):
        return _decision(
            request,
            route="local_process",
            hard_action="allow",
            utility_label="sufficient",
            reasons=(reasons or ["user requested local handling"]),
            rule_ids=rule_ids + ["explicit_local_handling_request"],
        )

    if not spans:
        utility = estimate_utility(request.text)
        if utility == "insufficient":
            return _decision(
                request,
                route="ask_clarification",
                hard_action="allow",
                utility_label=utility,
                reasons=["no sensitive spans detected", "insufficient task context"],
                rule_ids=rule_ids + ["utility_insufficient_requires_clarification"],
            )
        return _decision(
            request,
            route="delegate_sanitized_to_external_ai",
            hard_action="allow",
            utility_label=utility,
            reasons=["no sensitive spans detected"],
            rule_ids=rule_ids + ["safe_public_request_can_delegate"],
            advisory_route="delegate_sanitized_to_external_ai",
        )

    if "system_prompt" in labels:
        return _decision(
            request,
            route="deny_request",
            hard_action="deny_span",
            utility_label="insufficient",
            reasons=reasons + ["system prompt or hidden instruction extraction attempt"],
            rule_ids=rule_ids + ["system_prompt_never_crosses_boundary"],
        )

    if "prompt_injection" in labels and (labels & (SECRET_LABELS | CODE_LABELS | {"incident_detail", "system_prompt"})):
        return _decision(
            request,
            route="local_summary",
            hard_action="summarize_locally",
            utility_label="partial",
            reasons=reasons + ["prompt injection amplified by high-risk context"],
            rule_ids=rule_ids + ["prompt_injection_is_risk_amplifier"],
        )

    if "prompt_injection" in labels:
        return _decision(
            request,
            route="local_process",
            hard_action="summarize_locally",
            utility_label="partial",
            reasons=reasons + ["prompt injection treated as untrusted data, not policy authority"],
            rule_ids=rule_ids + ["prompt_injection_is_data_not_authority"],
        )

    if "incident_detail" in labels and labels & INFRA_LABELS:
        return _decision(
            request,
            route="local_summary",
            hard_action="summarize_locally",
            utility_label="partial",
            reasons=reasons + ["incident detail combined with internal infrastructure"],
            rule_ids=rule_ids + ["incident_topology_stays_local"],
        )

    if "incident_detail" in labels:
        return _decision(
            request,
            route="local_summary",
            hard_action="summarize_locally",
            utility_label="partial",
            reasons=reasons + ["incident detail summarized inside trusted boundary"],
            rule_ids=rule_ids + ["incident_detail_stays_local"],
        )

    if labels & CODE_LABELS:
        return _code_route(request, spans, labels, reasons, rule_ids)

    sanitized = sanitize_text(request.text, spans, route="delegate_sanitized_to_external_ai")
    utility = estimate_utility(sanitized)

    if utility == "insufficient":
        route = "local_summary" if labels & HIGH_RISK_LABELS else "ask_clarification"
        return _decision(
            request,
            route=route,
            hard_action="transform",
            utility_label=utility,
            reasons=reasons + ["transformed payload lacks enough utility for delegation"],
            rule_ids=rule_ids + ["utility_insufficient_blocks_delegation"],
        )

    route = advisory_route(request, spans)
    if route not in DELEGATION_ROUTES:
        route = "delegate_sanitized_to_external_ai"

    return _decision(
        request,
        route=route,
        hard_action="transform",
        utility_label=utility,
        reasons=reasons + ["transformed payload can preserve utility without raw sensitive spans"],
        rule_ids=rule_ids + ["transformed_payload_safety_plus_remaining_utility"],
        advisory_route=route,
    )


def _code_route(
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    labels: set[str],
    reasons: list[str],
    rule_ids: list[str],
) -> PolicyDecision:
    if labels & (SECRET_LABELS | {"incident_detail", "system_prompt"}):
        return _decision(
            request,
            route="local_summary",
            hard_action="summarize_locally",
            utility_label="partial",
            reasons=reasons + ["raw source code combined with high-risk context"],
            rule_ids=rule_ids + ["source_code_with_high_risk_context_stays_local"],
        )

    pseudocode_payload = sanitize_text(request.text, spans, route="delegate_pseudocode_to_external_ai")
    utility = estimate_utility(pseudocode_payload)
    if utility == "insufficient":
        return _decision(
            request,
            route="local_summary",
            hard_action="summarize_locally",
            utility_label=utility,
            reasons=reasons + ["raw source code removed but remaining utility is insufficient"],
            rule_ids=rule_ids + ["source_code_utility_insufficient"],
        )

    return _decision(
        request,
        route="delegate_pseudocode_to_external_ai",
        hard_action="summarize_locally",
        utility_label=utility,
        reasons=reasons + ["raw source code converted to pseudocode/generalized problem statement"],
        rule_ids=rule_ids + ["source_code_requires_pseudocode"],
        advisory_route="delegate_pseudocode_to_external_ai",
    )


def _decision(
    request: NormalizedRequest,
    route: str,
    hard_action: str,
    utility_label: str,
    reasons: list[str],
    rule_ids: list[str],
    advisory_route: Optional[str] = None,
) -> PolicyDecision:
    target_profile = request.target_profile if route in DELEGATION_ROUTES else None
    transport = request.transport if route in DELEGATION_ROUTES else "none"
    return PolicyDecision(
        route=route,
        target_profile=target_profile,
        transport=transport,
        hard_action=hard_action,
        utility_label=utility_label,
        reasons=reasons,
        rule_ids=rule_ids,
        advisory_route=advisory_route,
    )


def _reasons(spans: list[SensitiveSpan]) -> list[str]:
    counts = Counter(span.label for span in spans)
    return [f"{label}:{count}" for label, count in sorted(counts.items())]


def _requested_local_handling(text: str) -> bool:
    lowered = text.lower()
    return "local only" in lowered or "handle this locally" in lowered or "do not delegate" in lowered
