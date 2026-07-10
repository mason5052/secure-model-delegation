from __future__ import annotations

import re
from typing import Any

from .policy_config import PolicyConfig
from .request_model import NormalizedRequest, SensitiveSpan


TASK_INTENT_TERMS = {
    "debug",
    "error",
    "troubleshoot",
    "explain",
    "summarize",
    "draft",
    "rewrite",
    "review",
    "compare",
    "classify",
    "analyze",
    "check",
    "help",
    "prepare",
    "create",
    "suggest",
    "find",
    "identify",
    "diagnose",
    "assess",
    "describe",
    "produce",
    "evaluate",
    "investigate",
    "rephrase",
    "recommend",
    "determine",
}

ABSTRACT_PROBLEM_TERMS = {
    "401",
    "403",
    "timeout",
    "connect",
    "connection",
    "configuration",
    "config",
    "authentication",
    "authorization",
    "access",
    "control-flow",
    "security issue",
    "connectivity",
    "policy",
    "training",
}


def advisory_route(request: NormalizedRequest, spans: list[SensitiveSpan]) -> str:
    labels = {span.label for span in spans}
    if "source_code" in labels or "proprietary_code" in labels:
        return "delegate_pseudocode_to_external_ai"
    if "prompt_injection" in labels:
        return "local_summary"
    return "delegate_sanitized_to_external_ai"


def assess_utility(text: str) -> dict[str, object]:
    lowered = text.lower()
    has_intent = any(term in lowered for term in TASK_INTENT_TERMS)
    has_structure = any(term in lowered for term in ABSTRACT_PROBLEM_TERMS)
    placeholder_count = lowered.count("[")
    word_count = len(lowered.split())
    ambiguous_task = bool(re.search(r"\b(?:can you help|help with this|please help)\b", lowered))

    if not has_intent or placeholder_count >= 6 or ambiguous_task:
        label = "insufficient"
        score = 0.1
    elif has_structure:
        label = "sufficient"
        score = 1.0
    elif word_count < 8:
        label = "insufficient"
        score = 0.1
    elif word_count >= 14:
        label = "sufficient"
        score = 1.0
    else:
        label = "partial"
        score = 0.55
    return {
        "label": label,
        "score": score,
        "has_task_intent": has_intent,
        "has_abstract_structure": has_structure,
        "placeholder_count": placeholder_count,
        "word_count": word_count,
        "ambiguous_task": ambiguous_task,
    }


def estimate_utility(text: str) -> str:
    return str(assess_utility(text)["label"])


def score_allowed_routes(
    request: NormalizedRequest,
    spans: list[SensitiveSpan],
    candidates: set[str],
    route_payloads: dict[str, str],
    policy: PolicyConfig,
) -> dict[str, dict[str, Any]]:
    """Compute route-specific utility only after hard policy constrains routes."""
    scores: dict[str, dict[str, Any]] = {}
    context = request.metadata.get("utility_context", {})
    if not isinstance(context, dict):
        context = {}
    local_capability = _bounded(
        context.get("local_capability", policy.utility_defaults["local_capability"])
    )
    external_capability = _bounded(
        context.get("external_capability", policy.utility_defaults["external_capability"])
    )

    for route in sorted(candidates):
        payload = route_payloads.get(route, request.text)
        assessment = assess_utility(payload)
        task_adequacy = float(assessment["score"])
        information_retention = _information_retention(route, spans)
        model_capability_fit = (
            external_capability
            if route.startswith("delegate_")
            else local_capability
        )

        if route == "ask_clarification":
            task_adequacy = 1.0 if assessment["ambiguous_task"] else 0.25
            information_retention = 0.35
            model_capability_fit = 1.0
        elif route == "deny_request":
            task_adequacy = 0.0
            information_retention = 0.0
            model_capability_fit = 0.0
        elif route == "local_summary":
            task_adequacy = max(task_adequacy, 0.55)

        operational_cost = policy.route_operational_cost[route]
        weights = policy.utility_weights
        score = (
            weights["task_adequacy"] * task_adequacy
            + weights["information_retention"] * information_retention
            + weights["model_capability_fit"] * model_capability_fit
            - weights["operational_cost"] * operational_cost
        )
        scores[route] = {
            "score": round(score, 6),
            "task_adequacy": round(task_adequacy, 6),
            "information_retention": round(information_retention, 6),
            "model_capability_fit": round(model_capability_fit, 6),
            "operational_cost": round(operational_cost, 6),
            "utility_label": assessment["label"],
        }
    return scores


def select_highest_utility_route(
    scores: dict[str, dict[str, Any]],
    policy: PolicyConfig,
) -> str:
    if not scores:
        return "deny_request"
    return max(
        scores,
        key=lambda route: (
            float(scores[route]["score"]),
            policy.route_preference[route],
            route,
        ),
    )


def _information_retention(route: str, spans: list[SensitiveSpan]) -> float:
    if route == "local_process":
        return 1.0
    if route == "local_summary":
        return 0.55
    if route == "delegate_pseudocode_to_external_ai":
        return 0.65
    if route == "delegate_sanitized_to_external_ai":
        transformed = len([span for span in spans if span.start != span.end])
        return max(0.20, 1.0 - min(0.80, transformed * 0.10))
    if route == "ask_clarification":
        return 0.35
    return 0.0


def _bounded(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
