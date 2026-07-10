from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS = {
    "case_id",
    "benchmark_version",
    "split",
    "family",
    "template_id",
    "variant_id",
    "target_profile",
    "input_request",
    "risk_classes",
    "attack_family",
    "case_type",
    "is_adversarial",
    "expected_span_actions",
    "expected_route",
    "expected_transformation",
    "expected_utility",
    "leakage_oracle",
    "rule_based_utility_label",
    "utility_context",
    "ground_truth_evidence",
    "variation_axes",
    "conversation_turns",
    "rationale",
    "review_status",
}
FAMILIES = {f"F{index}" for index in range(1, 8)}
TARGETS = {"local_private", "approved_external_ai", "high_risk_external_ai"}
SPLITS = {"development", "template_evaluation", "challenge"}
ROUTES = {
    "local_process",
    "deny_request",
    "ask_clarification",
    "local_summary",
    "delegate_sanitized_to_external_ai",
    "delegate_pseudocode_to_external_ai",
}
CASE_TYPES = {
    "adversarial_evasion",
    "benign_public",
    "benign_stress",
    "prompt_injection",
    "routine_sensitive",
}
BANNED_MARKERS = ("zinus", "zinny", "customer production", "real credential")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Line {line_number} is not a JSON object")
            records.append(value)
    return records


def validate_dataset(cases: Iterable[dict[str, Any]], expected_count: int | None = None) -> dict[str, Any]:
    records = list(cases)
    errors: list[str] = []
    case_ids: set[str] = set()
    normalized_prompts: set[str] = set()
    template_splits: defaultdict[str, set[str]] = defaultdict(set)
    family_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    case_type_counts: Counter[str] = Counter()
    family_target_counts: Counter[str] = Counter()
    template_variations: defaultdict[str, set[str]] = defaultdict(set)

    if expected_count is not None and len(records) != expected_count:
        errors.append(f"Expected {expected_count} cases, found {len(records)}")

    for index, case in enumerate(records):
        missing = REQUIRED_FIELDS - set(case)
        if missing:
            errors.append(f"Record {index} missing fields: {sorted(missing)}")
            continue
        case_id = str(case["case_id"])
        if case_id in case_ids:
            errors.append(f"Duplicate case_id: {case_id}")
        case_ids.add(case_id)
        family = str(case["family"])
        split = str(case["split"])
        target = str(case["target_profile"])
        route = str(case["expected_route"])
        case_type = str(case["case_type"])
        if family not in FAMILIES:
            errors.append(f"Invalid family for {case_id}: {family}")
        if split not in SPLITS:
            errors.append(f"Invalid split for {case_id}: {split}")
        if target not in TARGETS:
            errors.append(f"Invalid target for {case_id}: {target}")
        if route not in ROUTES:
            errors.append(f"Invalid expected route for {case_id}: {route}")
        if case_type not in CASE_TYPES:
            errors.append(f"Invalid case type for {case_id}: {case_type}")
        expected_adversarial = case_type in {"adversarial_evasion", "prompt_injection"}
        if case["is_adversarial"] is not expected_adversarial:
            errors.append(
                f"Adversarial flag disagrees with case type for {case_id}: {case_type}"
            )
        if case["review_status"] != "pending":
            errors.append(f"Generated case must be pending human review: {case_id}")
        template_splits[str(case["template_id"])].add(split)
        variation_axes = case["variation_axes"]
        if not isinstance(variation_axes, dict) or not variation_axes:
            errors.append(f"Invalid variation_axes for {case_id}")
        else:
            template_variations[str(case["template_id"])].add(
                json.dumps(variation_axes, sort_keys=True)
            )
        if not isinstance(case["ground_truth_evidence"], list):
            errors.append(f"Invalid ground_truth_evidence for {case_id}")
        family_counts[family] += 1
        target_counts[target] += 1
        split_counts[split] += 1
        case_type_counts[case_type] += 1
        family_target_counts[f"{family}:{target}"] += 1

        combined = str(case["input_request"]) + json.dumps(case["conversation_turns"], sort_keys=True)
        normalized = re.sub(r"[^a-z0-9]", "", combined.lower())
        if normalized in normalized_prompts:
            errors.append(f"Normalized duplicate prompt: {case_id}")
        normalized_prompts.add(normalized)
        lowered = combined.lower()
        for marker in BANNED_MARKERS:
            if marker in lowered:
                errors.append(f"Banned non-synthetic marker in {case_id}: {marker}")

    for template_id, splits in template_splits.items():
        if len(splits) != 1:
            errors.append(f"Template appears in more than one split: {template_id}")

    if len(records) == 1400:
        expected_family = {family: 200 for family in sorted(FAMILIES)}
        expected_target = {
            "local_private": 469,
            "approved_external_ai": 469,
            "high_risk_external_ai": 462,
        }
        expected_split = {"development": 1120, "template_evaluation": 280}
        expected_case_types = {
            "adversarial_evasion": 120,
            "benign_public": 160,
            "benign_stress": 40,
            "prompt_injection": 260,
            "routine_sensitive": 820,
        }
        if dict(sorted(family_counts.items())) != expected_family:
            errors.append(f"Family distribution mismatch: {dict(family_counts)}")
        if dict(target_counts) != expected_target:
            errors.append(f"Target distribution mismatch: {dict(target_counts)}")
        if dict(split_counts) != expected_split:
            errors.append(f"Split distribution mismatch: {dict(split_counts)}")
        if dict(sorted(case_type_counts.items())) != expected_case_types:
            errors.append(f"Case type distribution mismatch: {dict(case_type_counts)}")
        for family in FAMILIES:
            expected = {"local_private": 67, "approved_external_ai": 67, "high_risk_external_ai": 66}
            actual = {target: family_target_counts[f"{family}:{target}"] for target in TARGETS}
            if actual != expected:
                errors.append(f"Family target distribution mismatch for {family}: {actual}")
        for template_id, signatures in template_variations.items():
            if len(signatures) < 8:
                errors.append(
                    f"Insufficient surface variation for {template_id}: {len(signatures)}"
                )
    elif len(records) == 210 and split_counts == {"challenge": 210}:
        expected_family = {family: 30 for family in sorted(FAMILIES)}
        expected_target = {
            "local_private": 70,
            "approved_external_ai": 70,
            "high_risk_external_ai": 70,
        }
        expected_case_types = {
            "adversarial_evasion": 12,
            "benign_public": 24,
            "benign_stress": 6,
            "prompt_injection": 36,
            "routine_sensitive": 132,
        }
        if dict(sorted(family_counts.items())) != expected_family:
            errors.append(f"Challenge family distribution mismatch: {dict(family_counts)}")
        if dict(target_counts) != expected_target:
            errors.append(f"Challenge target distribution mismatch: {dict(target_counts)}")
        if dict(sorted(case_type_counts.items())) != expected_case_types:
            errors.append(
                f"Challenge case type distribution mismatch: {dict(case_type_counts)}"
            )
        if len(template_splits) != 35:
            errors.append(f"Challenge must contain 35 templates, found {len(template_splits)}")
        for template_id, signatures in template_variations.items():
            if len(signatures) != 6:
                errors.append(
                    f"Challenge template {template_id} must contain six variations, "
                    f"found {len(signatures)}"
                )

    summary = {
        "valid": not errors,
        "errors": errors,
        "case_count": len(records),
        "unique_case_ids": len(case_ids),
        "normalized_duplicate_count": len(records) - len(normalized_prompts),
        "family_counts": dict(sorted(family_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "case_type_counts": dict(sorted(case_type_counts.items())),
        "template_count": len(template_splits),
        "template_split_isolation": all(len(value) == 1 for value in template_splits.values()),
        "minimum_variations_per_template": min(
            (len(value) for value in template_variations.values()),
            default=0,
        ),
    }
    if errors:
        raise ValueError("SMD-Bench validation failed:\n- " + "\n- ".join(errors[:30]))
    return summary
