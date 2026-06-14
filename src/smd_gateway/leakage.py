from __future__ import annotations

import re
from typing import Any


def find_direct_leakage(payload: str, leakage_oracle: Any) -> list[str]:
    oracle = _normalize_oracle(leakage_oracle)
    findings: list[str] = []

    for raw_span in oracle["must_not_contain"]:
        if not raw_span:
            continue
        if raw_span in payload:
            findings.append(f"exact:{raw_span}")
            continue
        if raw_span.lower() in payload.lower():
            findings.append(f"case_insensitive:{raw_span}")
            continue
        if _compact(raw_span) and _compact(raw_span) in _compact(payload):
            findings.append(f"whitespace_normalized:{raw_span}")

    for pattern in oracle["must_not_match_patterns"]:
        try:
            if re.search(pattern, payload, flags=re.IGNORECASE | re.MULTILINE):
                findings.append(f"pattern:{pattern}")
        except re.error as exc:
            findings.append(f"invalid_pattern:{pattern}:{exc}")

    return findings


def _normalize_oracle(leakage_oracle: Any) -> dict[str, list[str]]:
    if leakage_oracle is None:
        return {"must_not_contain": [], "must_not_match_patterns": []}

    if isinstance(leakage_oracle, list):
        return {"must_not_contain": [str(item) for item in leakage_oracle], "must_not_match_patterns": []}

    if isinstance(leakage_oracle, dict):
        return {
            "must_not_contain": [str(item) for item in leakage_oracle.get("must_not_contain", [])],
            "must_not_match_patterns": [
                str(item) for item in leakage_oracle.get("must_not_match_patterns", [])
            ],
        }

    return {"must_not_contain": [str(leakage_oracle)], "must_not_match_patterns": []}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
