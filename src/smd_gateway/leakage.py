from __future__ import annotations

import re
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Any
from urllib.parse import unquote


def find_direct_leakage(payload: str, leakage_oracle: Any) -> list[str]:
    return evaluate_leakage(payload, leakage_oracle)["direct"]


def evaluate_leakage(payload: str, leakage_oracle: Any) -> dict[str, list[str]]:
    oracle = _normalize_oracle(leakage_oracle)
    direct: list[str] = []
    for index, raw_span in enumerate(oracle["must_not_contain"]):
        if not raw_span:
            continue
        if raw_span in payload:
            direct.append(f"exact:span_{index}")
            continue
        if raw_span.lower() in payload.lower():
            direct.append(f"case_insensitive:span_{index}")
            continue
        if _compact(raw_span) and _compact(raw_span) in _compact(payload):
            direct.append(f"whitespace_normalized:span_{index}")
    for index, pattern in enumerate(oracle["must_not_match_patterns"]):
        try:
            if re.search(pattern, payload, flags=re.IGNORECASE | re.MULTILINE):
                direct.append(f"pattern:{index}")
        except re.error as exc:
            direct.append(f"invalid_pattern:{index}:{exc}")
    return {
        "direct": direct,
        "canonicalized": _canonicalized_findings(payload, oracle),
        "structural_code": _structural_findings(payload, oracle),
    }


def _normalize_oracle(leakage_oracle: Any) -> dict[str, list[str]]:
    if leakage_oracle is None:
        leakage_oracle = {}
    if isinstance(leakage_oracle, list):
        leakage_oracle = {"must_not_contain": leakage_oracle}
    if not isinstance(leakage_oracle, dict):
        leakage_oracle = {"must_not_contain": [str(leakage_oracle)]}
    return {
        "must_not_contain": [str(item) for item in leakage_oracle.get("must_not_contain", [])],
        "must_not_match_patterns": [str(item) for item in leakage_oracle.get("must_not_match_patterns", [])],
        "split_fragments": [str(item) for item in leakage_oracle.get("split_fragments", [])],
        "must_not_contain_code_tokens": [str(item) for item in leakage_oracle.get("must_not_contain_code_tokens", [])],
        "must_not_contain_code_lines": [str(item) for item in leakage_oracle.get("must_not_contain_code_lines", [])],
    }


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _canonicalized_findings(payload: str, oracle: dict[str, list[str]]) -> list[str]:
    findings: list[str] = []
    decoded_payloads = [payload, unquote(payload)] + _decoded_base64_segments(payload)
    canonical_payloads = [_canonical(value) for value in decoded_payloads]
    protected_values = list(oracle["must_not_contain"])
    if oracle["split_fragments"]:
        protected_values.append("".join(oracle["split_fragments"]))
    for index, raw in enumerate(protected_values):
        canonical = _canonical(raw)
        if len(canonical) >= 8 and any(canonical in candidate for candidate in canonical_payloads):
            findings.append(f"canonicalized:span_{index}")
    return findings


def _structural_findings(payload: str, oracle: dict[str, list[str]]) -> list[str]:
    findings: list[str] = []
    lowered = payload.lower()
    for index, token in enumerate(oracle["must_not_contain_code_tokens"]):
        if token and token.lower() in lowered:
            findings.append(f"code_token:{index}")
    compact_payload = _compact(payload)
    for index, line in enumerate(oracle["must_not_contain_code_lines"]):
        if line and _compact(line) in compact_payload:
            findings.append(f"code_line:{index}")
    return findings


def _decoded_base64_segments(payload: str) -> list[str]:
    decoded: list[str] = []
    pattern = r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{12,}={0,2}(?![A-Za-z0-9+/=])"
    for token in re.findall(pattern, payload):
        try:
            padded = token + "=" * ((4 - len(token) % 4) % 4)
            decoded.append(b64decode(padded, validate=True).decode("utf-8", errors="ignore"))
        except (BinasciiError, ValueError):
            continue
    return decoded
