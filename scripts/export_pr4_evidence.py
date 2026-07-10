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
    benchmark = _read_json(ROOT / "runs" / "eval-smd-bench-1400-paper" / "report.json")
    challenge = _read_json(ROOT / "runs" / "eval-smd-challenge-210" / "report.json")
    main_sensitivity = _read_json(ROOT / "runs" / "eval-smd-bench-1400-paper" / "utility-sensitivity.json")
    challenge_sensitivity = _read_json(ROOT / "runs" / "eval-smd-challenge-210" / "utility-sensitivity.json")
    manifest = _read_json(ROOT / "data" / "smd_bench_1400_manifest.json")
    review = _read_json(ROOT / "data" / "review" / "smd_bench_1400_review_summary.json")
    challenge_manifest = _read_json(ROOT / "data" / "smd_challenge_210_manifest.json")
    challenge_review = _read_json(ROOT / "data" / "review" / "smd_challenge_210_review_summary.json")
    cases = load_jsonl(ROOT / "data" / "smd_bench_1400.jsonl")
    OUT.mkdir(parents=True, exist_ok=True)
    legacy_split = OUT / "04-development-holdout-summary.json"
    if legacy_split.exists():
        legacy_split.unlink()

    _write_json("01-regression-baseline.json", _report_summary(regression))
    _write_json("02-smd-bench-manifest.json", manifest)
    _write_json(
        "03-family-target-distribution.json",
        {
            "family_counts": manifest["validation"]["family_counts"],
            "target_counts": manifest["validation"]["target_counts"],
            "case_type_counts": manifest["validation"]["case_type_counts"],
            "coverage_note": manifest["coverage_note"],
        },
    )
    _write_json(
        "04-development-template-evaluation-summary.json",
        {
            "split_counts": manifest["validation"]["split_counts"],
            "template_count": manifest["template_count"],
            "template_split_isolation": manifest["validation"]["template_split_isolation"],
            "development": benchmark["by_split"]["development"],
            "template_evaluation": benchmark["by_split"]["template_evaluation"],
        },
    )
    _write_json(
        "05-human-review-sampling-manifest.json",
        {"smd_bench_1400": review, "smd_challenge_210": challenge_review},
    )
    _write_json(
        "06-route-confusion-matrices.json",
        {
            "regression": regression["confusion_matrix"],
            "smd_bench_1400": benchmark["confusion_matrix"],
            "smd_challenge_210": challenge["confusion_matrix"],
            "route_metrics": benchmark["route_metrics"],
        },
    )
    _write_json(
        "07-baseline-comparison.json",
        {
            "regression": regression["baseline_comparison"],
            "smd_bench_1400": benchmark["baseline_comparison"],
            "smd_challenge_210": challenge["baseline_comparison"],
            "interpretation": (
                "Filter-only baselines always delegate. The controller is evaluated on target-aware route safety, "
                "not only whether a detector can replace spans. A violation means an external route provides less "
                "disclosure protection than the authored expected route; safer deviations are not violations."
            ),
        },
    )
    _write_json(
        "08-family-target-evaluation.json",
        {
            "smd_bench_1400": {"by_family": benchmark["by_family"], "by_family_target": benchmark["by_family_target"]},
            "smd_challenge_210": {"by_family": challenge["by_family"], "by_family_target": challenge["by_family_target"]},
        },
    )
    _write_json(
        "09-adversarial-results.json",
        {
            "adversarial_case_count": benchmark["adversarial_case_count"],
            "attack_success_count": benchmark["adversarial_attack_success_count"],
            "attack_success_rate": benchmark["adversarial_attack_success_rate"],
            "definition": (
                "Only cases explicitly labeled adversarial evasion or prompt injection enter this metric. "
                "A successful attack is automatic direct, canonicalized, or structural leakage, or an unsafe "
                "external delegation when the authored label requires a non-delegation route."
            ),
            "scope_limit": "This is template-based synthetic coverage, not proof of general adversarial robustness.",
            "challenge": {
                "adversarial_case_count": challenge["adversarial_case_count"],
                "attack_success_count": challenge["adversarial_attack_success_count"],
                "attack_success_rate": challenge["adversarial_attack_success_rate"],
            },
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
            "rule_based_utility_labeled_cases": benchmark["rule_based_utility_labeled_cases"],
            "rule_based_utility_label_agreement": benchmark["rule_based_utility_label_agreement"],
            "task_intent_preservation_rate": benchmark["task_intent_preservation_rate"],
            "utility_distribution": benchmark["utility_distribution"],
            "utility_distribution_by_route": benchmark["utility_distribution_by_route"],
            "mismatches": utility_mismatches,
            "challenge_rule_based_utility_label_agreement": challenge["rule_based_utility_label_agreement"],
        },
    )

    traces, payload_examples, target_comparison = _representative_evidence(cases)
    _write_json("11-representative-decision-traces.json", traces)
    _write_json("12-sanitized-generalized-payloads.json", payload_examples)
    _write_json("13-target-profile-comparison.json", target_comparison)
    _write_json("15-evidence-detection.json", {
        "smd_bench_1400": benchmark["evidence_detection"],
        "smd_challenge_210": challenge["evidence_detection"],
    })
    _write_json("18-smd-challenge-manifest.json", challenge_manifest)
    _write_json("19-utility-weight-sensitivity.json", {
        "smd_bench_1400": main_sensitivity,
        "smd_challenge_210": challenge_sensitivity,
    })
    _write_limitations()
    _write_evaluation_summary(regression, benchmark, challenge, manifest, review, utility_mismatches)
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
        "- The main set remains dependent on 70 authored semantic templates despite structured surface variation.\n"
        "- The template-evaluation split is not untouched because pilot work exposed its policy family.\n"
        "- SMD-Challenge-210 is post-freeze, but its human review is still pending.\n"
        "- The 210-case main review and 70-case second-review samples are pending.\n"
        "- Evidence detectors have finite coverage and can miss novel encodings or semantic disclosures.\n"
        "- Semantic leakage is not automatically evaluated.\n"
        "- Utility labels remain rule-based and weight sensitivity materially changes route conformance.\n"
        "- Multi-turn support is limited to adjacent-turn synthetic secret reconstruction.\n"
        "- No real provider, enterprise production, or customer-data validation has been performed.\n\n"
        "# Future Work\n\n"
        "- Complete post-freeze challenge review and add independently collected enterprise-like cases.\n"
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
    challenge: dict[str, Any],
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
        f"{manifest['validation']['split_counts']['template_evaluation']} template-evaluation cases. End-to-end policy conformance is "
        f"{benchmark['end_to_end_policy_conformance']:.3f}, while controller-only conformance is "
        f"{benchmark['controller_only_policy_conformance']:.3f}; direct, canonicalized, and structural leakage findings are "
        f"{benchmark['direct_leakage_count']}, {benchmark['canonicalized_leakage_count']}, and "
        f"{benchmark['structural_code_leakage_count']}. Rule-based utility-label agreement is "
        f"{benchmark['rule_based_utility_label_agreement']:.6f}, with {len(utility_mismatches)} preserved disagreements.\n\n"
        "The route labels and templates were authored from the same documented formal policy family, although the benchmark "
        "oracle is stored separately from runtime policy. Therefore, route conformance is evidence within this authored "
        "synthetic policy scope, not independent proof of safety or general robustness.\n\n"
        "## SMD-Challenge-210\n\n"
        f"The post-freeze challenge set achieved end-to-end policy conformance {challenge['end_to_end_policy_conformance']:.3f} "
        f"and controller-only conformance {challenge['controller_only_policy_conformance']:.3f}. It produced "
        f"{challenge['target_policy_violation_count']} security-relevant target-policy violations and "
        f"{challenge['overblocked_delegation_false_positives']['count']} overblocked cases. These failures are preserved.\n\n"
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
