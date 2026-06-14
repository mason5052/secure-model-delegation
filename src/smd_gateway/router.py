from __future__ import annotations

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


def estimate_utility(text: str) -> str:
    lowered = text.lower()
    has_intent = any(term in lowered for term in TASK_INTENT_TERMS)
    has_structure = any(term in lowered for term in ABSTRACT_PROBLEM_TERMS)
    placeholder_count = lowered.count("[")
    word_count = len(lowered.split())

    if not has_intent:
        return "insufficient"

    if placeholder_count >= 6:
        return "insufficient"

    if has_structure:
        return "sufficient"

    if word_count < 8:
        return "insufficient"

    if word_count >= 14:
        return "sufficient"

    return "partial"
