from __future__ import annotations

import base64
import re
from binascii import Error as BinasciiError
from typing import Optional
from urllib.parse import unquote

from .policy_config import PolicyConfig, load_policy_config
from .request_model import NormalizedRequest, SensitiveSpan


# Detectors provide evidence only. Severity, span action, route permission, and
# conflict priority are loaded from policy.yaml and remain controller authority.
DETECTOR_RULES: list[dict[str, str]] = [
    {
        "label": "api_key",
        "pattern": r"\b(?:sk-(?:test|proj|live)?-?[A-Za-z0-9_-]{8,}|(?:API|OPENAI|ANTHROPIC|SERVICE)_?KEY\s*=\s*[A-Za-z0-9._-]{8,})\b",
        "detector": "regex_secret",
        "provider_group": "structured_regex",
    },
    {
        "label": "api_key",
        "pattern": r"\bA\s*P\s*I\s*[_ -]?\s*K\s*E\s*Y\s*[:=]\s*(?:[A-Za-z0-9]\s*){10,}\b",
        "detector": "regex_obfuscated_secret",
        "provider_group": "structured_regex",
    },
    {
        "label": "auth_token",
        "pattern": r"\bBearer\s+[A-Za-z0-9._-]{10,}\b",
        "detector": "regex_token",
        "provider_group": "structured_regex",
    },
    {
        "label": "config_secret",
        "pattern": r"\b(?:[A-Z][A-Z0-9]*_)*(?:PASSWORD|SECRET|TOKEN|KEY)\s*=\s*[A-Za-z0-9_@#$%./:-]{6,}\b",
        "detector": "regex_config",
        "provider_group": "structured_regex",
    },
    {
        "label": "pii_name",
        "pattern": r"\b[A-Z][a-z]+ [A-Z][a-z]+(?=(?:\s+(?:at|with|called|reported)|,))",
        "detector": "regex_pii",
        "provider_group": "structured_regex",
    },
    {
        "label": "pii_email",
        "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "detector": "regex_pii",
        "provider_group": "structured_regex",
    },
    {
        "label": "pii_phone",
        "pattern": r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b",
        "detector": "regex_pii",
        "provider_group": "structured_regex",
    },
    {
        "label": "private_ip",
        "pattern": r"\b(?:(?:10)(?:\.\d{1,3}){3}|(?:192\.168)(?:\.\d{1,3}){2}|(?:172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2})\b",
        "detector": "regex_infra",
        "provider_group": "structured_regex",
    },
    {
        "label": "internal_hostname",
        "pattern": r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:internal|local|corp)\b",
        "detector": "regex_infra",
        "provider_group": "structured_regex",
    },
    {
        "label": "internal_infrastructure",
        "pattern": r"\b(?:admin subnet|privileged subnet|internal topology|service mesh|vpn-gw-[a-z0-9-]+|svc-[a-z0-9-]+|prod-[a-z0-9-]+)\b",
        "detector": "regex_infra_context",
        "provider_group": "contextual_detector",
    },
    {
        "label": "source_code",
        "pattern": (
            r"```[\s\S]*?```|"
            r"\bfunction\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\{[^}]*\}|"
            r"\b(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^;\n]+;"
            r"(?:\s*return\s+[^;\n]+;)?|"
            r"\b(?:def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b"
        ),
        "detector": "regex_code",
        "provider_group": "contextual_detector",
    },
    {
        "label": "proprietary_code",
        "pattern": r"\b(?:private repository|private repo|private payment module|internal payment module|proprietary code|unreleased algorithm|internal source code)\b",
        "detector": "custom_code_context",
        "provider_group": "contextual_detector",
    },
    {
        "label": "incident_detail",
        "pattern": r"\b(?:incident timeline|attacker|lateral movement|detection rule|security alert|exfiltration|forensic log|privileged admin)\b",
        "detector": "custom_incident_context",
        "provider_group": "contextual_detector",
    },
    {
        "label": "system_prompt",
        "pattern": r"\b(?:hidden router instructions|internal prompt|system prompt|internal agent instructions|reveal the system prompt)\b",
        "detector": "custom_control_logic",
        "provider_group": "contextual_detector",
    },
    {
        "label": "prompt_injection",
        "pattern": r"\b(?:ignore previous|ignore all previous|system override|send all api keys|send all secrets|bypass policy|disable the gateway|reveal.*system prompt)\b",
        "detector": "custom_prompt_injection",
        "provider_group": "contextual_detector",
    },
    {
        "label": "prompt_injection",
        "pattern": r"\b(?:i\s*g\s*n\s*o\s*r\s*e\s+previous|b\s*y\s*p\s*a\s*s\s+s\s+policy|s\s*e\s*n\s*d\s+all\s+secrets)\b",
        "detector": "custom_obfuscated_prompt_injection",
        "provider_group": "contextual_detector",
    },
    {
        "label": "prompt_injection",
        "pattern": r"\b(?:base64|encoded|decode)[^\n.]{0,100}(?:aWdub3Jl|c2VuZCBhbGwgc2VjcmV0cw|YnlwYXNz)[A-Za-z0-9+/=]*",
        "detector": "custom_encoded_prompt_injection",
        "provider_group": "contextual_detector",
    },
]


def detect_sensitive_spans(
    request: NormalizedRequest,
    policy: Optional[PolicyConfig] = None,
    provider_mode: str = "all",
    include_cross_turn: bool = True,
) -> list[SensitiveSpan]:
    policy = policy or load_policy_config()
    allowed_groups = _provider_groups(provider_mode)
    spans = _detect_in_text(request.text, policy, allowed_groups)
    spans.extend(_detect_encoded_secrets(request.text, policy, allowed_groups))
    if include_cross_turn and request.conversation_turns:
        cross_turn = _detect_cross_turn_secrets(request, policy, allowed_groups)
        if cross_turn:
            request.metadata["cross_turn_sensitive"] = True
            spans.extend(cross_turn)
    return _dedupe_spans(spans)


def _detect_in_text(
    text: str,
    policy: PolicyConfig,
    allowed_groups: set[str],
) -> list[SensitiveSpan]:
    spans: list[SensitiveSpan] = []
    for rule in DETECTOR_RULES:
        if rule["provider_group"] not in allowed_groups:
            continue
        class_policy = policy.class_policy(rule["label"])
        flags = 0 if rule["label"] == "pii_name" else re.IGNORECASE
        for match in re.finditer(rule["pattern"], text, flags=flags):
            spans.append(
                SensitiveSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    label=rule["label"],
                    detector=rule["detector"],
                    policy_action=class_policy.default_span_action,
                    severity=class_policy.severity,
                    provider_group=rule["provider_group"],
                )
            )
    return spans


def _detect_encoded_secrets(
    text: str,
    policy: PolicyConfig,
    allowed_groups: set[str],
) -> list[SensitiveSpan]:
    if "structured_regex" not in allowed_groups:
        return []
    findings: list[SensitiveSpan] = []
    candidates: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\S*%[0-9A-Fa-f]{2}\S*", text):
        candidates.append((match.start(), match.end(), unquote(match.group(0))))
    for match in re.finditer(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])", text):
        try:
            token = match.group(0)
            padded = token + "=" * ((4 - len(token) % 4) % 4)
            decoded = base64.b64decode(padded, validate=True).decode("utf-8", errors="ignore")
        except (BinasciiError, ValueError):
            continue
        candidates.append((match.start(), match.end(), decoded))
    for start, end, decoded in candidates:
        for decoded_span in _detect_in_text(decoded, policy, {"structured_regex"}):
            if decoded_span.label not in {"api_key", "auth_token", "config_secret"}:
                continue
            findings.append(
                SensitiveSpan(
                    start=start,
                    end=end,
                    text=text[start:end],
                    label=decoded_span.label,
                    detector="canonicalized_encoded_secret",
                    policy_action=decoded_span.policy_action,
                    severity=decoded_span.severity,
                    provider_group="structured_regex",
                )
            )
    return findings


def _provider_groups(provider_mode: str) -> set[str]:
    if provider_mode in {"regex_secret_pii_filter", "structured_regex"}:
        return {"structured_regex"}
    if provider_mode in {"all", "all_detectors"}:
        return {"structured_regex", "contextual_detector"}
    raise ValueError(f"Unknown evidence provider mode: {provider_mode}")


def _detect_cross_turn_secrets(
    request: NormalizedRequest,
    policy: PolicyConfig,
    allowed_groups: set[str],
) -> list[SensitiveSpan]:
    findings: list[SensitiveSpan] = []
    texts = [chunk.text for chunk in request.conversation_turns]
    for left, right in zip(texts, texts[1:]):
        reconstructed = re.sub(r"\s+", "", left[-160:] + right[:160])
        for span in _detect_in_text(reconstructed, policy, allowed_groups):
            if span.label not in {"api_key", "auth_token", "config_secret"}:
                continue
            findings.append(
                SensitiveSpan(
                    start=0,
                    end=0,
                    text=span.text,
                    label=span.label,
                    detector="cross_turn_secret_reconstruction",
                    policy_action=span.policy_action,
                    severity=span.severity,
                    provider_group="cross_turn",
                )
            )
    return findings


def _dedupe_spans(spans: list[SensitiveSpan]) -> list[SensitiveSpan]:
    seen: set[tuple[int, int, str, str]] = set()
    unique: list[SensitiveSpan] = []
    for span in sorted(spans, key=lambda item: (item.start, -(item.end - item.start), item.label)):
        key = (span.start, span.end, span.label, span.detector)
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return unique
