from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .policy_config import PolicyConfig, load_policy_config
from .request_model import SensitiveSpan


def sanitize_text(
    text: str,
    spans: list[SensitiveSpan],
    route: str = "delegate_sanitized_to_external_ai",
    policy: Optional[PolicyConfig] = None,
) -> str:
    policy = policy or load_policy_config()
    counters: defaultdict[str, int] = defaultdict(int)
    replacements: list[tuple[int, int, str]] = []

    for span in sorted(_non_overlapping_spans(spans), key=lambda item: (item.start, item.end)):
        if span.start == span.end:
            continue
        counters[span.label] += 1
        replacements.append(
            (span.start, span.end, _replacement_for(span, counters[span.label], route, policy))
        )

    sanitized = text
    for start, end, placeholder in sorted(replacements, key=lambda item: item[0], reverse=True):
        sanitized = sanitized[:start] + placeholder + sanitized[end:]

    if route == "delegate_pseudocode_to_external_ai":
        sanitized = _append_generalized_context(sanitized)
    return sanitized


def transformation_type_for_route(route: str) -> str:
    return {
        "delegate_sanitized_to_external_ai": "redaction_and_generalization",
        "delegate_pseudocode_to_external_ai": "generalized_problem_statement",
        "local_summary": "local_summary",
        "ask_clarification": "clarification",
        "deny_request": "deny",
        "local_process": "none",
    }.get(route, "none")


def _replacement_for(
    span: SensitiveSpan,
    index: int,
    route: str,
    policy: PolicyConfig,
) -> str:
    class_policy = policy.class_policy(span.label)
    if span.policy_action == "allow":
        return span.text
    if span.policy_action == "remove":
        return ""
    if span.label == "prompt_injection":
        return "[PROMPT_INJECTION_TEXT_REMOVED]"
    if span.label == "source_code" and route == "delegate_pseudocode_to_external_ai":
        return f"[GENERALIZED_CODE_{index}]"
    if span.label in {"source_code", "proprietary_code", "incident_detail", "system_prompt"}:
        base = _indexed_placeholder(class_policy.placeholder or "[SENSITIVE]", index)
        return base.replace("]", "_LOCAL_ONLY]")
    return _indexed_placeholder(class_policy.placeholder or "[SENSITIVE]", index)


def _append_generalized_context(text: str) -> str:
    marker = (
        "\n\n[GENERALIZED_PROBLEM_STATEMENT]\n"
        "A private implementation detail was replaced with a high-level security question. "
        "Review the abstract control-flow or design issue without requiring raw source code."
    )
    if "[GENERALIZED_PROBLEM_STATEMENT]" in text:
        return text
    return text + marker


def _indexed_placeholder(value: str, index: int) -> str:
    if value.startswith("[") and value.endswith("]"):
        return value[:-1] + f"_{index}]"
    return f"[{value}_{index}]"


def _non_overlapping_spans(spans: list[SensitiveSpan]) -> list[SensitiveSpan]:
    selected: list[SensitiveSpan] = []
    for span in sorted(spans, key=lambda item: (item.start, -(item.end - item.start), item.label)):
        if span.start == span.end:
            selected.append(span)
            continue
        if any(span.start < existing.end and existing.start < span.end for existing in selected):
            continue
        selected.append(span)
    return selected
