from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Optional

from .evidence import detect_sensitive_spans
from .leakage import evaluate_leakage
from .main import process_request
from .normalizer import assemble_request
from .policy import DELEGATION_ROUTES
from .policy_config import load_policy_config
from .request_model import RequestBundle, SourceChunk
from .sanitizer import sanitize_text


BASELINES = (
    "no_gateway",
    "regex_secret_pii_filter",
    "all_detectors_filter_only",
    "policy_bounded_controller",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def add_regression_metadata(cases: list[dict[str, Any]], sidecar_path: Path) -> list[dict[str, Any]]:
    if not sidecar_path.is_file():
        return cases
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    adversarial = sidecar.get("adversarial_cases", {})
    enriched: list[dict[str, Any]] = []
    for case in cases:
        record = dict(case)
        record.setdefault("split", "regression")
        record.setdefault("family", "legacy_regression")
        record.setdefault("target_profile", "approved_external_ai")
        record.setdefault("risk_classes", [])
        record.setdefault("conversation_turns", [])
        record.setdefault("attack_family", adversarial.get(record["case_id"], "none"))
        enriched.append(record)
    return enriched


def evaluate_cases(
    cases: Iterable[dict[str, Any]],
    run_dir: Path,
    benchmark_name: str,
) -> dict[str, Any]:
    records = list(cases)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    confusion: defaultdict[str, Counter[str]] = defaultdict(Counter)
    baseline_accumulators = {name: _empty_baseline() for name in BASELINES}

    for case in records:
        bundle = _bundle_from_case(case)
        started = perf_counter()
        result = process_request(
            bundle,
            leakage_oracle=case.get("leakage_oracle", {}),
            run_dir=run_dir,
        )
        latency_ms = (perf_counter() - started) * 1000
        latencies.append(latency_ms)
        expected_route = str(case.get("expected_route", ""))
        confusion[expected_route][result.route] += 1
        utility = _utility_result(case, result.utility_label, result.delegated_payload)
        row = {
            "case_id": case["case_id"],
            "split": case.get("split", "regression"),
            "family": case.get("family", "legacy_regression"),
            "target_profile": case.get("target_profile", "approved_external_ai"),
            "attack_family": case.get("attack_family", "none"),
            "expected_route": expected_route,
            "actual_route": result.route,
            "expected_utility": utility["expected_label"],
            "actual_utility": result.utility_label,
            "utility_agreement": utility["agreement"],
            "task_intent_preserved": utility["task_intent_preserved"],
            "detected_labels": result.detected_labels,
            "transformation_type": result.transformation_type,
            "policy_version": result.policy_version,
            "conflict_rule_id": result.conflict_rule_id,
            "direct_leakage": result.direct_leakage_found,
            "canonicalized_leakage": result.canonicalized_leakage_found,
            "structural_code_leakage": result.structural_code_leakage_found,
            "latency_ms": round(latency_ms, 3),
        }
        results.append(row)
        _accumulate_controller(baseline_accumulators["policy_bounded_controller"], row)

        for baseline in BASELINES[:-1]:
            baseline_started = perf_counter()
            payload = _baseline_payload(baseline, bundle)
            baseline_latency = (perf_counter() - baseline_started) * 1000
            leakage = evaluate_leakage(payload or "", case.get("leakage_oracle", {}))
            _accumulate_filter_baseline(
                baseline_accumulators[baseline],
                payload,
                leakage,
                baseline_latency,
            )

    route_metrics = _route_metrics(confusion)
    main_summary = _aggregate_rows(results, latencies)
    group_tables = _group_tables(results)
    return {
        "benchmark": benchmark_name,
        **main_summary,
        "route_metrics": route_metrics,
        "confusion_matrix": {
            expected: dict(sorted(actual.items()))
            for expected, actual in sorted(confusion.items())
        },
        "baseline_comparison": {
            name: _finish_baseline(value, len(records))
            for name, value in baseline_accumulators.items()
        },
        "by_split": group_tables["split"],
        "by_family": group_tables["family"],
        "by_target_profile": group_tables["target_profile"],
        "by_family_target": group_tables["family_target"],
        "semantic_leakage": {
            "automatic_evaluation": False,
            "manual_review_required": True,
            "note": "Automatic results cover direct, canonicalized/encoded, and structural code-detail leakage only.",
        },
        "results": results,
    }


def _bundle_from_case(case: dict[str, Any]) -> RequestBundle:
    return RequestBundle(
        case_id=str(case["case_id"]),
        user_prompt=str(case["input_request"]),
        target_profile=str(case.get("target_profile", "approved_external_ai")),
        transport=str(case.get("transport", "simulated_external_endpoint")),
        conversation_turns=[
            SourceChunk(source=str(turn.get("source", "user")), text=str(turn.get("text", "")))
            for turn in case.get("conversation_turns", [])
        ],
    )


def _baseline_payload(name: str, bundle: RequestBundle) -> Optional[str]:
    request = assemble_request(bundle)
    if name == "no_gateway":
        return request.text
    policy = load_policy_config()
    mode = "regex_secret_pii_filter" if name == "regex_secret_pii_filter" else "all"
    spans = detect_sensitive_spans(request, policy=policy, provider_mode=mode)
    return sanitize_text(request.text, spans, route="delegate_sanitized_to_external_ai", policy=policy)


def _utility_result(case: dict[str, Any], actual_label: str, payload: Optional[str]) -> dict[str, Any]:
    oracle = case.get("utility_oracle")
    if not isinstance(oracle, dict) or "expected_label" not in oracle:
        return {"expected_label": None, "agreement": None, "task_intent_preserved": None}
    expected = str(oracle["expected_label"])
    terms = [str(item).lower() for item in oracle.get("required_terms_any", [])]
    if not terms or payload is None:
        intent_preserved = True
    else:
        lowered = payload.lower()
        intent_preserved = any(term in lowered for term in terms)
    return {
        "expected_label": expected,
        "agreement": actual_label == expected,
        "task_intent_preserved": intent_preserved,
    }


def _empty_baseline() -> dict[str, Any]:
    return {
        "delegated_cases": 0,
        "direct_leakage_findings": 0,
        "direct_leakage_cases": 0,
        "canonicalized_leakage_findings": 0,
        "canonicalized_leakage_cases": 0,
        "structural_code_leakage_findings": 0,
        "structural_code_leakage_cases": 0,
        "latencies": [],
    }


def _accumulate_filter_baseline(
    accumulator: dict[str, Any],
    payload: Optional[str],
    leakage: dict[str, list[str]],
    latency_ms: float,
) -> None:
    if payload is not None:
        accumulator["delegated_cases"] += 1
    for key, metric in (
        ("direct", "direct_leakage"),
        ("canonicalized", "canonicalized_leakage"),
        ("structural_code", "structural_code_leakage"),
    ):
        accumulator[f"{metric}_findings"] += len(leakage[key])
        if leakage[key]:
            accumulator[f"{metric}_cases"] += 1
    accumulator["latencies"].append(latency_ms)


def _accumulate_controller(accumulator: dict[str, Any], row: dict[str, Any]) -> None:
    delegated = row["actual_route"] in DELEGATION_ROUTES
    if delegated:
        accumulator["delegated_cases"] += 1
    for field, metric in (
        ("direct_leakage", "direct_leakage"),
        ("canonicalized_leakage", "canonicalized_leakage"),
        ("structural_code_leakage", "structural_code_leakage"),
    ):
        accumulator[f"{metric}_findings"] += len(row[field])
        if row[field]:
            accumulator[f"{metric}_cases"] += 1
    accumulator["latencies"].append(float(row["latency_ms"]))


def _finish_baseline(value: dict[str, Any], count: int) -> dict[str, Any]:
    latencies = value.pop("latencies")
    result = dict(value)
    for metric in ("direct_leakage", "canonicalized_leakage", "structural_code_leakage"):
        result[f"{metric}_case_rate"] = (
            0.0 if count == 0 else round(result[f"{metric}_cases"] / count, 6)
        )
    result["latency_ms_p50"] = round(_percentile(latencies, 0.50), 3)
    result["latency_ms_p95"] = round(_percentile(latencies, 0.95), 3)
    return result


def _aggregate_rows(rows: list[dict[str, Any]], latencies: list[float]) -> dict[str, Any]:
    count = len(rows)
    route_correct = sum(row["expected_route"] == row["actual_route"] for row in rows)
    expected_delegation = [row["expected_route"] in DELEGATION_ROUTES for row in rows]
    actual_delegation = [row["actual_route"] in DELEGATION_ROUTES for row in rows]
    unsafe = [row for row, expected, actual in zip(rows, expected_delegation, actual_delegation) if not expected and actual]
    overblocked = [row for row, expected, actual in zip(rows, expected_delegation, actual_delegation) if expected and not actual]
    adversarial = [row for row in rows if row["attack_family"] != "none"]
    attack_successes = [
        row
        for row in adversarial
        if row["direct_leakage"]
        or row["canonicalized_leakage"]
        or row["structural_code_leakage"]
        or (row["expected_route"] not in DELEGATION_ROUTES and row["actual_route"] in DELEGATION_ROUTES)
    ]
    utility_counts = Counter(row["actual_utility"] for row in rows)
    route_utility: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        route_utility[row["actual_route"]][row["actual_utility"]] += 1
    return {
        "case_count": count,
        "delegated_cases": sum(actual_delegation),
        "route_accuracy_or_policy_conformance": 0.0 if count == 0 else round(route_correct / count, 6),
        "unsafe_delegation_false_negatives": {"count": len(unsafe), "case_ids": [row["case_id"] for row in unsafe]},
        "overblocked_delegation_false_positives": {"count": len(overblocked), "case_ids": [row["case_id"] for row in overblocked]},
        "direct_leakage_count": sum(len(row["direct_leakage"]) for row in rows),
        "canonicalized_leakage_count": sum(len(row["canonicalized_leakage"]) for row in rows),
        "structural_code_leakage_count": sum(len(row["structural_code_leakage"]) for row in rows),
        "adversarial_case_count": len(adversarial),
        "adversarial_attack_success_count": len(attack_successes),
        "adversarial_attack_success_rate": 0.0 if not adversarial else round(len(attack_successes) / len(adversarial), 6),
        "utility_oracle_labeled_cases": sum(row["utility_agreement"] is not None for row in rows),
        "utility_oracle_agreement": _optional_rate([row["utility_agreement"] for row in rows]),
        "task_intent_preservation_rate": _optional_rate([row["task_intent_preserved"] for row in rows]),
        "utility_distribution": dict(sorted(utility_counts.items())),
        "utility_distribution_by_route": {route: dict(sorted(values.items())) for route, values in sorted(route_utility.items())},
        "clarification_rate": 0.0 if count == 0 else round(sum(row["actual_route"] == "ask_clarification" for row in rows) / count, 6),
        "route_distribution": dict(sorted(Counter(row["actual_route"] for row in rows).items())),
        "latency_ms": {"p50": round(_percentile(latencies, 0.50), 3), "p95": round(_percentile(latencies, 0.95), 3)},
    }


def _route_metrics(confusion: dict[str, Counter[str]]) -> dict[str, Any]:
    routes = sorted(set(confusion) | {route for values in confusion.values() for route in values})
    per_route: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for route in routes:
        tp = confusion[route][route]
        fp = sum(values[route] for expected, values in confusion.items() if expected != route)
        fn = sum(count for actual, count in confusion[route].items() if actual != route)
        precision = 0.0 if tp + fp == 0 else tp / (tp + fp)
        recall = 0.0 if tp + fn == 0 else tp / (tp + fn)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        f1_values.append(f1)
        per_route[route] = {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6), "support": tp + fn}
    return {"per_route": per_route, "macro_f1": 0.0 if not f1_values else round(sum(f1_values) / len(f1_values), 6)}


def _group_tables(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, defaultdict[str, list[dict[str, Any]]]] = {
        "split": defaultdict(list),
        "family": defaultdict(list),
        "target_profile": defaultdict(list),
        "family_target": defaultdict(list),
    }
    for row in rows:
        groups["split"][row["split"]].append(row)
        groups["family"][row["family"]].append(row)
        groups["target_profile"][row["target_profile"]].append(row)
        groups["family_target"][f"{row['family']}:{row['target_profile']}"] .append(row)
    output: dict[str, dict[str, Any]] = {}
    for group_name, values in groups.items():
        output[group_name] = {}
        for key, group_rows in sorted(values.items()):
            output[group_name][key] = _compact_group_summary(group_rows)
    return output


def _compact_group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    return {
        "case_count": count,
        "policy_conformance": round(sum(row["expected_route"] == row["actual_route"] for row in rows) / count, 6),
        "unsafe_delegation_count": sum(row["expected_route"] not in DELEGATION_ROUTES and row["actual_route"] in DELEGATION_ROUTES for row in rows),
        "overblocked_count": sum(row["expected_route"] in DELEGATION_ROUTES and row["actual_route"] not in DELEGATION_ROUTES for row in rows),
        "direct_leakage_count": sum(len(row["direct_leakage"]) for row in rows),
        "canonicalized_leakage_count": sum(len(row["canonicalized_leakage"]) for row in rows),
        "structural_code_leakage_count": sum(len(row["structural_code_leakage"]) for row in rows),
        "utility_agreement": _optional_rate([row["utility_agreement"] for row in rows]),
        "route_distribution": dict(sorted(Counter(row["actual_route"] for row in rows).items())),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return ordered[index]


def _optional_rate(values: list[Optional[bool]]) -> Optional[float]:
    labeled = [value for value in values if value is not None]
    if not labeled:
        return None
    return round(sum(bool(value) for value in labeled) / len(labeled), 6)
