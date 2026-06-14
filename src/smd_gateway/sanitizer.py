from __future__ import annotations

from collections import defaultdict

from .request_model import SensitiveSpan


PLACEHOLDER_PREFIX = {
    "api_key": "API_KEY",
    "auth_token": "AUTH_TOKEN",
    "config_secret": "CONFIG_SECRET",
    "pii_name": "PERSON",
    "pii_email": "EMAIL",
    "pii_phone": "PHONE",
    "private_ip": "PRIVATE_IP",
    "internal_hostname": "INTERNAL_HOST",
    "internal_infrastructure": "INTERNAL_INFRA",
    "source_code": "SOURCE_CODE",
    "proprietary_code": "PROPRIETARY_CODE",
    "incident_detail": "INCIDENT_DETAIL",
    "system_prompt": "SYSTEM_PROMPT",
    "prompt_injection": "PROMPT_INJECTION",
}


def sanitize_text(text: str, spans: list[SensitiveSpan], route: str = "delegate_sanitized_to_external_ai") -> str:
    counters: defaultdict[str, int] = defaultdict(int)
    replacements: list[tuple[int, int, str]] = []

    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        counters[span.label] += 1
        replacements.append((span.start, span.end, _replacement_for(span, counters[span.label], route)))

    sanitized = text
    for start, end, placeholder in sorted(replacements, key=lambda x: x[0], reverse=True):
        sanitized = sanitized[:start] + placeholder + sanitized[end:]

    if route == "delegate_pseudocode_to_external_ai":
        sanitized = _append_pseudocode_context(sanitized)

    return sanitized


def _replacement_for(span: SensitiveSpan, index: int, route: str) -> str:
    if span.label == "prompt_injection":
        return "[PROMPT_INJECTION_TEXT_REMOVED]"

    if span.label == "source_code" and route == "delegate_pseudocode_to_external_ai":
        return f"[PSEUDOCODE_SUMMARY_{index}]"

    if span.label in {"source_code", "proprietary_code", "incident_detail", "system_prompt"}:
        prefix = PLACEHOLDER_PREFIX.get(span.label, "SENSITIVE")
        return f"[{prefix}_LOCAL_ONLY_{index}]"

    prefix = PLACEHOLDER_PREFIX.get(span.label, "SENSITIVE")
    return f"[{prefix}_{index}]"


def _append_pseudocode_context(text: str) -> str:
    marker = (
        "\n\n[GENERALIZED_PROBLEM_STATEMENT]\n"
        "A private implementation detail was replaced with a high-level security question. "
        "Review the abstract control-flow or design issue without requiring raw source code."
    )
    if "[GENERALIZED_PROBLEM_STATEMENT]" in text:
        return text
    return text + marker
