from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smd_gateway.evaluation import _bundle_from_case, load_jsonl
from smd_gateway.main import process_request


OUT = ROOT / "docs" / "evidence" / "pr4"


def main() -> None:
    regression = _read_json(ROOT / "runs" / "eval" / "regression_report.json")
    benchmark = _read_json(ROOT / "runs" / "eval-smd-bench-1400" / "report.json")
    manifest = _read_json(ROOT / "data" / "smd_bench_1400_manifest.json")
    review = _read_json(ROOT / "data" / "review" / "smd_bench_1400_review_summary.json")
    cases = load_jsonl(ROOT / "data" / "smd_bench_1400.jsonl")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    _write_json("01-regression-baseline.json", _report_summary(regression))
    _write_json("02-smd-bench-manifest.json", manifest)
    _write_json(
        "03-family-target-distribution.json",
        {
            "family_counts": manifest["validation"]["family_counts"],
            "target_counts": manifest["validation"]["target_counts"],
            "coverage_note": manifest["coverage_note"],
        },
    )
    _write_json(
        "04-development-holdout-summary.json",
        {
            "split_counts": manifest["validation"]["split_counts"],
            "template_count": manifest["template_count"],
            "template_split_isolation": manifest["validation"]["template_split_isolation"],
            "development": benchmark["by_split"]["development"],
            "holdout": benchmark["by_split"]["holdout"],
        },
    )
    _write_json("05-human-review-sampling-manifest.json", review)
    _write_json(
        "06-route-confusion-matrices.json",
        {
            "regression": regression["confusion_matrix"],
            "smd_bench_1400": benchmark["confusion_matrix"],
            "route_metrics": benchmark["route_metrics"],
        },
    )
    _write_json(
        "07-baseline-comparison.json",
        {
            "regression": regression["baseline_comparison"],
            "smd_bench_1400": benchmark["baseline_comparison"],
            "interpretation": (
                "Filter-only baselines always delegate. The controller is evaluated on target-aware route safety, "
                "not only whether a detector can replace spans."
            ),
        },
    )
    _write_json(
        "08-family-target-evaluation.json",
        {"by_family": benchmark["by_family"], "by_family_target": benchmark["by_family_target"]},
    )
    _write_json(
        "09-adversarial-results.json",
        {
            "adversarial_case_count": benchmark["adversarial_case_count"],
            "attack_success_count": benchmark["adversarial_attack_success_count"],
            "attack_success_rate": benchmark["adversarial_attack_success_rate"],
            "definition": (
                "A successful attack is automatic direct, canonicalized, or structural leakage, or an unsafe "
                "external delegation when the oracle requires a non-delegation route."
            ),
            "scope_limit": "This is template-based synthetic coverage, not proof of general adversarial robustness.",
        },
    )
    utility_mismatches = [
        {
            "case_id": row["case_id"],
            "family": row["family"],
            "target_profile": row["target_profile"],
            "expected_utility": row["expected_utility"],
            "actual_utility": row["actual_utility"],
        }
        for row in benchmark["results"]
        if row["utility_agreement"] is False
    ]
    _write_json(
        "10-utility-results.json",
        {
            "utility_oracle_labeled_cases": benchmark["utility_oracle_labeled_cases"],
            "utility_oracle_agreement": benchmark["utility_oracle_agreement"],
            "task_intent_preservation_rate": benchmark["task_intent_preservation_rate"],
            "utility_distribution": benchmark["utility_distribution"],
            "utility_distribution_by_route": benchmark["utility_distribution_by_route"],
            "mismatches": utility_mismatches,
        },
    )

    traces, payload_examples, target_comparison = _representative_evidence(cases)
    _write_json("11-representative-decision-traces.json", traces)
    _write_json("12-sanitized-generalized-payloads.json", payload_examples)
    _write_json("13-target-profile-comparison.json", target_comparison)
    _write_limitations()
    _write_evaluation_summary(regression, benchmark, manifest, review, utility_mismatches)
    print(json.dumps({"output_directory": "docs/evidence/pr4", "file_count": len(list(OUT.iterdir()))}, indent=2))


def _representative_evidence(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    desired = (
        "url_encoded_secret",
        "authorization_code",
        "system_prompt_extraction",
        "split_secret_across_turns",
        "none",
        "incident_timeline",
    )
    selected: list[dict[str, Any]] = []
    for attack in desired:
        match = next(
            case
            for case in cases
            if case["attack_family"] == attack
            and case["target_profile"] == "approved_external_ai"
        )
        selected.append(match)

    run_dir = ROOT / "runs" / "evidence-export"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    traces: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for case in selected:
        result = process_request(
            _bundle_from_case(case),
            leakage_oracle=case["leakage_oracle"],
            run_dir=run_dir,
        )
        traces.append(
            {
                "case_id": case["case_id"],
                "family": case["family"],
                "attack_family": case["attack_family"],
                "expected_route": case["expected_route"],
                "actual_route": result.route,
                "detected_labels": result.detected_labels,
                "span_actions": result.span_actions,
                "candidate_routes": result.candidate_routes,
                "eliminated_routes": result.eliminated_routes,
                "conflict_rule_id": result.conflict_rule_id,
                "conflict_priority": result.conflict_priority,
                "transformation_type": result.transformation_type,
                "policy_version": result.policy_version,
                "decision_trace": result.decision_trace,
            }
        )
        if result.delegated_payload is not None:
            payloads.append(
                {
                    "case_id": case["case_id"],
                    "route": result.route,
                    "transformation_type": result.transformation_type,
                    "delegated_payload": result.delegated_payload,
                    "direct_leakage_found": result.direct_leakage_found,
                    "canonicalized_leakage_found": result.canonicalized_leakage_found,
                    "structural_code_leakage_found": result.structural_code_leakage_found,
                }
            )

    target_cases = [case for case in cases if case["template_id"] == "F3-T01"]
    comparison: list[dict[str, Any]] = []
    for target in ("local_private", "approved_external_ai", "high_risk_external_ai"):
        case = next(item for item in target_cases if item["target_profile"] == target)
        result = process_request(
            _bundle_from_case(case),
            leakage_oracle=case["leakage_oracle"],
            run_dir=run_dir,
        )
        comparison.append(
            {
                "target_profile": target,
                "route": result.route,
                "transformation_type": result.transformation_type,
                "delegated": result.delegated_payload is not None,
                "detected_labels": result.detected_labels,
                "conflict_rule_id": result.conflict_rule_id,
            }
        )
    return traces, payloads, comparison


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    excluded = {"results", "by_family_target"}
    return {key: value for key, value in report.items() if key not in excluded}


def _write_limitations() -> None:
    (OUT / "14-current-limitations-and-future-work.md").write_text(
        "# Current Limitations\n\n"
        "- SMD-Bench-1400 is synthetic and coverage-balanced; it does not estimate real workload frequency.\n"
        "- Cases remain dependent on 70 authored semantic templates.\n"
        "- The 210-case human review sample is pending and no human agreement claim is made.\n"
        "- Evidence detectors have finite coverage and can miss novel encodings or semantic disclosures.\n"
        "- Semantic leakage is not automatically evaluated.\n"
        "- Utility labels are heuristic; six generated cases currently disagree with the independent utility oracle.\n"
        "- Multi-turn support is limited to adjacent-turn synthetic secret reconstruction.\n"
        "- No real provider, enterprise production, or customer-data validation has been performed.\n\n"
        "# Future Work\n\n"
        "- Evaluate an independently collected enterprise-like benchmark.\n"
        "- Complete human annotation and measure inter-rater agreement.\n"
        "- Evaluate an optional ML advisory router that cannot override policy.\n"
        "- Add a semantic leakage evaluator with independently validated criteria.\n"
        "- Run optional sanitized-only provider smoke tests.\n"
        "- Expand language-aware code abstraction beyond deterministic generalization.\n"
        "- Study policy lifecycle, versioning, and stakeholder validation.\n",
        encoding="utf-8",
    )


def _write_evaluation_summary(
    regression: dict[str, Any],
    benchmark: dict[str, Any],
    manifest: dict[str, Any],
    review: dict[str, Any],
    utility_mismatches: list[dict[str, Any]],
) -> None:
    (OUT / "00-evaluation-summary.md").write_text(
        "# PR4 Public Evaluation Evidence\n\n"
        "Evidence first, policy authority always.\n\n"
        "## Regression\n\n"
        f"The preserved 63-case regression set achieved policy conformance {regression['route_accuracy_or_policy_conformance']:.3f} "
        f"with {regression['direct_leakage_count']} direct leakage findings. Independent utility labels do not exist "
        "for this legacy set, so utility agreement is reported as not applicable.\n\n"
        "## SMD-Bench-1400\n\n"
        f"The generated dataset contains {manifest['case_count']} cases across {manifest['template_count']} semantic templates, "
        f"with {manifest['validation']['split_counts']['development']} development cases and "
        f"{manifest['validation']['split_counts']['holdout']} locked holdout cases. Current policy conformance is "
        f"{benchmark['route_accuracy_or_policy_conformance']:.3f}; direct, canonicalized, and structural leakage findings are "
        f"{benchmark['direct_leakage_count']}, {benchmark['canonicalized_leakage_count']}, and "
        f"{benchmark['structural_code_leakage_count']}. Utility-oracle agreement is "
        f"{benchmark['utility_oracle_agreement']:.6f}, with {len(utility_mismatches)} preserved disagreements.\n\n"
        "The route labels and templates were authored from the same documented formal policy family, although the benchmark "
        "oracle is stored separately from runtime policy. Therefore, 100% route conformance is policy-conformance evidence "
        "within this synthetic template scope, not independent proof of safety or general robustness.\n\n"
        "## Human Review\n\n"
        f"The stratified review sample contains {review['sample_count']} cases. All remain pending; no case is claimed as "
        "human approved.\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required evaluation artifact does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
