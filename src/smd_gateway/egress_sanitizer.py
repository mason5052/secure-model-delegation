from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .policy_config import PolicyConfig, load_policy_config
from .request_model import SensitiveSpan
from .sanitizer import _append_generalized_context, _non_overlapping_spans, _replacement_for


@dataclass(frozen=True)
class EgressSanitizationResult:
    text: str
    placeholder_to_original: dict[str, str]


def sanitize_egress_with_map(
    text: str,
    spans: list[SensitiveSpan],
    route: str = "delegate_sanitized_to_external_ai",
    policy: Optional[PolicyConfig] = None,
) -> EgressSanitizationResult:
    policy = policy or load_policy_config()
    counters: defaultdict[str, int] = defaultdict(int)
    stable_placeholders: dict[tuple[str, str], str] = {}
    placeholder_to_original: dict[str, str] = {}
    replacements: list[tuple[int, int, str]] = []

    for span in sorted(_non_overlapping_spans(spans), key=lambda item: (item.start, item.end)):
        if span.start == span.end:
            continue
        key = (span.label, span.text)
        replacement = stable_placeholders.get(key)
        if replacement is None:
            counters[span.label] += 1
            replacement = _replacement_for(span, counters[span.label], route, policy)
            stable_placeholders[key] = replacement
            if _is_reversible_placeholder(span, replacement, route):
                placeholder_to_original[replacement] = span.text
        replacements.append((span.start, span.end, replacement))

    sanitized = text
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        sanitized = sanitized[:start] + replacement + sanitized[end:]
    if route == "delegate_pseudocode_to_external_ai":
        sanitized = _append_generalized_context(sanitized)
    return EgressSanitizationResult(
        text=sanitized,
        placeholder_to_original=placeholder_to_original,
    )


def restore_local_placeholders(
    text: str,
    placeholder_to_original: dict[str, str],
) -> str:
    restored = text
    for placeholder, original in sorted(
        placeholder_to_original.items(), key=lambda item: len(item[0]), reverse=True
    ):
        restored = restored.replace(placeholder, original)
    return restored


def _is_reversible_placeholder(span: SensitiveSpan, replacement: str, route: str) -> bool:
    if not replacement or replacement == span.text:
        return False
    if route == "delegate_pseudocode_to_external_ai":
        return False
    return span.policy_action == "replace_with_placeholder"
