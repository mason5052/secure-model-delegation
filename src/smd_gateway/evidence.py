from __future__ import annotations

import re

from .request_model import NormalizedRequest, SensitiveSpan


# Evidence providers are intentionally supporting components. The research
# contribution is the policy-bounded controller that consumes this evidence and
# resolves span-level actions into a request-level delegation route.
DETECTOR_RULES: list[dict[str, str]] = [
    {
        "label": "api_key",
        "pattern": r"\b(?:sk-(?:test|proj|live)?-?[A-Za-z0-9_-]{8,}|(?:API|OPENAI|ANTHROPIC|SERVICE)_?KEY\s*=\s*[A-Za-z0-9._-]{8,})\b",
        "detector": "regex_secret",
        "action": "replace_with_placeholder",
        "severity": "high",
    },
    {
        "label": "auth_token",
        "pattern": r"\bBearer\s+[A-Za-z0-9._-]{10,}\b",
        "detector": "regex_token",
        "action": "replace_with_placeholder",
        "severity": "high",
    },
    {
        "label": "config_secret",
        "pattern": r"\b(?:DB_)?(?:PASSWORD|SECRET|TOKEN|KEY)\s*=\s*[A-Za-z0-9_@#$%./:-]{6,}\b",
        "detector": "regex_config",
        "action": "replace_with_placeholder",
        "severity": "high",
    },
    {
        "label": "pii_name",
        "pattern": r"\b[A-Z][a-z]+ [A-Z][a-z]+(?=\s+(?:at|,|with|called|reported))",
        "detector": "regex_pii",
        "action": "replace_with_placeholder",
        "severity": "medium",
    },
    {
        "label": "pii_email",
        "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "detector": "regex_pii",
        "action": "replace_with_placeholder",
        "severity": "medium",
    },
    {
        "label": "pii_phone",
        "pattern": r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b",
        "detector": "regex_pii",
        "action": "replace_with_placeholder",
        "severity": "medium",
    },
    {
        "label": "private_ip",
        "pattern": r"\b(?:(?:10)(?:\.\d{1,3}){3}|(?:192\.168)(?:\.\d{1,3}){2}|(?:172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2})\b",
        "detector": "regex_infra",
        "action": "generalize",
        "severity": "medium",
    },
    {
        "label": "internal_hostname",
        "pattern": r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:internal|local|corp)\b",
        "detector": "regex_infra",
        "action": "generalize",
        "severity": "medium",
    },
    {
        "label": "internal_infrastructure",
        "pattern": r"\b(?:admin subnet|privileged subnet|internal topology|service mesh|vpn-gw-[a-z0-9-]+|svc-[a-z0-9-]+|prod-[a-z0-9-]+)\b",
        "detector": "regex_infra_context",
        "action": "generalize",
        "severity": "medium",
    },
    {
        "label": "source_code",
        "pattern": r"```[\s\S]*?```|\b(?:def|function|class|const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\b|return\s+[A-Za-z0-9_().+\-/*\[\]\"']+",
        "detector": "regex_code",
        "action": "summarize_locally",
        "severity": "high",
    },
    {
        "label": "proprietary_code",
        "pattern": r"\b(?:private repository|private repo|private payment module|internal payment module|proprietary code|unreleased algorithm|internal source code)\b",
        "detector": "custom_code_context",
        "action": "summarize_locally",
        "severity": "high",
    },
    {
        "label": "incident_detail",
        "pattern": r"\b(?:incident timeline|attacker|lateral movement|detection rule|security alert|exfiltration|forensic log|privileged admin)\b",
        "detector": "custom_incident_context",
        "action": "summarize_locally",
        "severity": "high",
    },
    {
        "label": "system_prompt",
        "pattern": r"\b(?:hidden router instructions|internal prompt|system prompt|internal agent instructions|reveal the system prompt)\b",
        "detector": "custom_control_logic",
        "action": "deny_span",
        "severity": "critical",
    },
    {
        "label": "prompt_injection",
        "pattern": r"\b(?:ignore previous|ignore all previous|system override|send all api keys|send all secrets|bypass policy|disable the gateway|reveal.*system prompt)\b",
        "detector": "custom_prompt_injection",
        "action": "summarize_locally",
        "severity": "medium",
    },
]


def detect_sensitive_spans(request: NormalizedRequest) -> list[SensitiveSpan]:
    spans: list[SensitiveSpan] = []
    for rule in DETECTOR_RULES:
        for match in re.finditer(rule["pattern"], request.text, flags=re.IGNORECASE):
            spans.append(
                SensitiveSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    label=rule["label"],
                    detector=rule["detector"],
                    policy_action=rule["action"],
                    severity=rule["severity"],
                )
            )
    return _dedupe_spans(spans)


def _dedupe_spans(spans: list[SensitiveSpan]) -> list[SensitiveSpan]:
    seen: set[tuple[int, int, str]] = set()
    unique: list[SensitiveSpan] = []
    for span in sorted(spans, key=lambda s: (s.start, -(s.end - s.start), s.label)):
        key = (span.start, span.end, span.label)
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return unique
