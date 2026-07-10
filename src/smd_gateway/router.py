from __future__ import annotations

import re

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
