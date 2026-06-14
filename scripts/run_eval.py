from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smd_gateway import process_request
from smd_gateway.evidence import detect_sensitive_spans
from smd_gateway.leakage import find_direct_leakage
from smd_gateway.normalizer import assemble_request
from smd_gateway.request_model import RequestBundle
from smd_gateway.sanitizer import sanitize_text


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
    route_correct = 0
    route_counts: Counter[str] = Counter()
    utility_counts: Counter[str] = Counter()

    for case in cases:
        bundle = RequestBundle(
            case_id=case["case_id"],
            user_prompt=case["input_request"],
            target_profile=case.get("target_profile", "external_ai"),
            transport=case.get("transport", "simulated_external_endpoint"),
        )
        result = process_request(
            bundle,
            leakage_oracle=case.get("leakage_oracle", {}),
            run_dir=run_dir,
        )
        if result.delegated_payload is not None:
            delegated_count += 1
        if result.leakage_found:
            leaked_count += len(result.leakage_found)
        if result.route == case.get("expected_route"):
            route_correct += 1

        route_counts[result.route] += 1
        utility_counts[result.utility_label] += 1
        results.append(
            {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "expected_route": case.get("expected_route"),
                "actual_route": result.route,
                "utility_label": result.utility_label,
                "detected_labels": result.detected_labels,
                "leakage_found": result.leakage_found,
            }
        )

    baseline_comparison = _run_baselines(cases)

    summary = {
        "benchmark_count": len(cases),
        "delegated_cases": delegated_count,
        "route_accuracy": route_correct / len(cases),
        "direct_leakage_count": leaked_count,
        "direct_leakage_rate": 0.0 if leaked_count == 0 else leaked_count / len(cases),
        "utility_label_counts": dict(sorted(utility_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "baseline_comparison": baseline_comparison,
        "simulated_endpoint_log": str(run_dir / "simulated_external_payloads.jsonl"),
        "audit_log": str(run_dir / "audit.jsonl"),
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))


def _run_baselines(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for name in ("no_gateway", "regex_only", "detector_only"):
        leaked_count = 0
        delegated_cases = 0
        for case in cases:
            payload = _baseline_payload(name, case)
            if payload is not None:
                delegated_cases += 1
                leaked_count += len(find_direct_leakage(payload, case.get("leakage_oracle", {})))
        outputs[name] = {
            "delegated_cases": delegated_cases,
            "direct_leakage_count": leaked_count,
            "direct_leakage_rate": 0.0 if leaked_count == 0 else leaked_count / len(cases),
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


if __name__ == "__main__":
    main()
