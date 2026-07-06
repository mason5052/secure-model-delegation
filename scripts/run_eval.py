from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smd_gateway import process_request
from smd_gateway.evidence import detect_sensitive_spans
from smd_gateway.leakage import find_direct_leakage
from smd_gateway.normalizer import assemble_request
from smd_gateway.request_model import RequestBundle
from smd_gateway.sanitizer import sanitize_text


DELEGATION_ROUTES = {
    "delegate_sanitized_to_external_ai",
    "delegate_pseudocode_to_external_ai",
}

ADVERSARIAL_CATEGORY_TERMS = (
    "prompt_injection",
    "obfuscated",
    "encoded",
    "bypass",
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def main() -> None:
    run_dir = ROOT / "runs" / "eval"
    if run_dir.exists():
        shutil.rmtree(run_dir)

    cases = load_cases(ROOT / "data" / "benchmark_cases.jsonl")
    results = []
    delegated_count = 0
    leaked_count = 0
    leaked_case_count = 0
    route_correct = 0
    route_counts: Counter[str] = Counter()
    utility_counts: Counter[str] = Counter()
    utility_preservation_counts: Counter[str] = Counter()
    controller_latencies_ms: list[float] = []
    no_gateway_latencies_ms: list[float] = []
    route_false_positives: list[dict[str, str]] = []
    route_false_negatives: list[dict[str, str]] = []
    route_mismatches: list[dict[str, str]] = []
    adversarial_case_count = 0
    adversarial_bypass_successes = 0

    for case in cases:
        bundle = RequestBundle(
            case_id=case["case_id"],
            user_prompt=case["input_request"],
            target_profile=case.get("target_profile", "external_ai"),
            transport=case.get("transport", "simulated_external_endpoint"),
        )
        controller_start = perf_counter()
        result = process_request(
            bundle,
            leakage_oracle=case.get("leakage_oracle", {}),
            run_dir=run_dir,
        )
        controller_latencies_ms.append((perf_counter() - controller_start) * 1000)

        no_gateway_start = perf_counter()
        find_direct_leakage(case["input_request"], case.get("leakage_oracle", {}))
        no_gateway_latencies_ms.append((perf_counter() - no_gateway_start) * 1000)

        expected_route = case.get("expected_route")
        expected_delegation = expected_route in DELEGATION_ROUTES
        actual_delegation = result.delegated_payload is not None

        if result.delegated_payload is not None:
            delegated_count += 1
        if result.leakage_found:
            leaked_count += len(result.leakage_found)
            leaked_case_count += 1
        if result.route == expected_route:
            route_correct += 1
        else:
            route_mismatches.append(
                {
                    "case_id": case["case_id"],
                    "category": str(case.get("category")),
                    "expected_route": str(expected_route),
                    "actual_route": result.route,
                }
            )

        if expected_delegation and not actual_delegation:
            route_false_positives.append(
                {
                    "case_id": case["case_id"],
                    "category": str(case.get("category")),
                    "expected_route": str(expected_route),
                    "actual_route": result.route,
                }
            )
        if not expected_delegation and actual_delegation:
            route_false_negatives.append(
                {
                    "case_id": case["case_id"],
                    "category": str(case.get("category")),
                    "expected_route": str(expected_route),
                    "actual_route": result.route,
                }
            )

        if _is_adversarial_case(case):
            adversarial_case_count += 1
            if result.leakage_found or (not expected_delegation and actual_delegation):
                adversarial_bypass_successes += 1

        route_counts[result.route] += 1
        utility_counts[result.utility_label] += 1
        utility_preservation_counts[
            f"{'delegated' if actual_delegation else 'not_delegated'}_{result.utility_label}"
        ] += 1
        results.append(
            {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "expected_route": expected_route,
                "actual_route": result.route,
                "utility_label": result.utility_label,
                "detected_labels": result.detected_labels,
                "leakage_found": result.leakage_found,
                "latency_ms": round(controller_latencies_ms[-1], 3),
            }
        )

    baseline_comparison = _run_baselines(cases)

    summary = {
        "benchmark_count": len(cases),
        "delegated_cases": delegated_count,
        "route_accuracy": route_correct / len(cases),
        "direct_leakage_count": leaked_count,
        "direct_leakage_case_count": leaked_case_count,
        "direct_leakage_case_rate": 0.0 if leaked_case_count == 0 else leaked_case_count / len(cases),
        "direct_leakage_findings_per_case": 0.0 if leaked_count == 0 else leaked_count / len(cases),
        "direct_leakage_findings_per_delegated_case": 0.0
        if delegated_count == 0
        else leaked_count / delegated_count,
        "false_positives_overblocked_delegation": {
            "count": len(route_false_positives),
            "cases": route_false_positives,
        },
        "false_negatives_unsafe_delegation": {
            "count": len(route_false_negatives),
            "cases": route_false_negatives,
        },
        "route_mismatches": {
            "count": len(route_mismatches),
            "cases": route_mismatches,
        },
        "utility_label_counts": dict(sorted(utility_counts.items())),
        "utility_preservation_summary": dict(sorted(utility_preservation_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "latency_ms": {
            "no_gateway_average": round(_average(no_gateway_latencies_ms), 3),
            "no_gateway_median": round(median(no_gateway_latencies_ms), 3),
            "policy_controller_average": round(_average(controller_latencies_ms), 3),
            "policy_controller_median": round(median(controller_latencies_ms), 3),
            "average_overhead": round(
                _average(controller_latencies_ms) - _average(no_gateway_latencies_ms), 3
            ),
        },
        "adversarial_bypass_resistance": {
            "adversarial_cases": adversarial_case_count,
            "successful_bypasses": adversarial_bypass_successes,
            "resistance_rate": 1.0
            if adversarial_case_count == 0
            else round(1 - (adversarial_bypass_successes / adversarial_case_count), 4),
        },
        "baseline_comparison": baseline_comparison,
        "simulated_endpoint_log": "runs/eval/simulated_external_payloads.jsonl",
        "audit_log": "runs/eval/audit.jsonl",
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))


def _run_baselines(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for name in ("no_gateway", "regex_only", "detector_only"):
        leaked_count = 0
        leaked_case_count = 0
        delegated_cases = 0
        for case in cases:
            payload = _baseline_payload(name, case)
            if payload is not None:
                delegated_cases += 1
                findings = find_direct_leakage(payload, case.get("leakage_oracle", {}))
                leaked_count += len(findings)
                if findings:
                    leaked_case_count += 1
        outputs[name] = {
            "delegated_cases": delegated_cases,
            "direct_leakage_count": leaked_count,
            "direct_leakage_case_count": leaked_case_count,
            "direct_leakage_case_rate": 0.0 if leaked_case_count == 0 else leaked_case_count / len(cases),
            "direct_leakage_findings_per_case": 0.0 if leaked_count == 0 else leaked_count / len(cases),
        }
    outputs["policy_bounded_controller"] = {
        "note": "See main evaluation metrics for route-aware controller results."
    }
    return outputs


def _baseline_payload(name: str, case: dict[str, Any]) -> Optional[str]:
    if name == "no_gateway":
        return case["input_request"]

    bundle = RequestBundle(case_id=case["case_id"], user_prompt=case["input_request"])
    request = assemble_request(bundle)
    spans = detect_sensitive_spans(request)

    if name == "regex_only":
        return sanitize_text(request.text, spans, route="delegate_sanitized_to_external_ai")

    if name == "detector_only":
        return sanitize_text(request.text, spans, route="delegate_sanitized_to_external_ai")

    return None


def _is_adversarial_case(case: dict[str, Any]) -> bool:
    category = str(case.get("category", "")).lower()
    return any(term in category for term in ADVERSARIAL_CATEGORY_TERMS)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


if __name__ == "__main__":
    main()
