from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from smd_bench import generator
from smd_bench.generator import (
    generate_challenge_dataset,
    generate_dataset,
    select_human_review_sample,
    select_second_reviewer_sample,
)
from smd_bench.egress_challenge import generate_egress_challenge_dataset
from smd_bench.schema import validate_dataset
from smd_gateway.evaluation import _is_target_policy_violation, evaluate_cases


def _digest(records: list[dict]) -> str:
    content = "".join(json.dumps(item, sort_keys=True, ensure_ascii=True) + "\n" for item in records)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _without_latency(value):
    if isinstance(value, dict):
        return {
            key: _without_latency(item)
            for key, item in value.items()
            if key not in {"latency_ms", "latency_ms_p50", "latency_ms_p95"}
        }
    if isinstance(value, list):
        return [_without_latency(item) for item in value]
    return value


class SmdBenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_generator_is_deterministic(self) -> None:
        first = generate_dataset(20)
        second = generate_dataset(20)
        self.assertEqual(_digest(first), _digest(second))

    def test_generator_seed_changes_synthetic_values(self) -> None:
        original_seed = generator.GENERATOR_SEED
        try:
            first_prompt = generate_dataset(1)[0]["input_request"]
            generator.GENERATOR_SEED = original_seed + 1
            second_prompt = generate_dataset(1)[0]["input_request"]
        finally:
            generator.GENERATOR_SEED = original_seed
        self.assertNotEqual(first_prompt, second_prompt)

    def test_dataset_checksum_uses_canonical_records(self) -> None:
        records = generate_dataset(2)
        first = generator.dataset_sha256(records)
        round_tripped = json.loads(json.dumps(records, ensure_ascii=True))
        second = generator.dataset_sha256(round_tripped)
        self.assertEqual(first, second)

    def test_pilot_and_full_schema_validation(self) -> None:
        pilot = [case for case in generate_dataset(2) if case["split"] == "development"]
        pilot_summary = validate_dataset(pilot, expected_count=112)
        self.assertTrue(pilot_summary["valid"])
        self.assertEqual(pilot_summary["normalized_duplicate_count"], 0)
        self.assertEqual(set(pilot_summary["split_counts"]), {"development"})

        full = generate_dataset(20)
        full_summary = validate_dataset(full, expected_count=1400)
        self.assertTrue(full_summary["valid"])
        self.assertEqual(full_summary["family_counts"], {f"F{index}": 200 for index in range(1, 8)})
        self.assertEqual(
            full_summary["target_counts"],
            {"approved_external_ai": 469, "high_risk_external_ai": 462, "local_private": 469},
        )
        self.assertEqual(
            full_summary["split_counts"],
            {"development": 1120, "template_evaluation": 280},
        )
        self.assertTrue(full_summary["template_split_isolation"])
        self.assertEqual(full_summary["minimum_variations_per_template"], 20)
        self.assertTrue(all(case["ground_truth_evidence"] or not case["risk_classes"] for case in full))

    def test_human_review_sample_is_stratified_and_pending(self) -> None:
        sample = select_human_review_sample(generate_dataset(20))
        self.assertEqual(len(sample), 210)
        self.assertEqual(Counter(item["family"] for item in sample), {f"F{i}": 30 for i in range(1, 8)})
        self.assertEqual(
            Counter(item["target_profile"] for item in sample),
            {"local_private": 70, "approved_external_ai": 70, "high_risk_external_ai": 70},
        )
        self.assertEqual(
            Counter(item["split"] for item in sample),
            {"development": 105, "template_evaluation": 105},
        )
        self.assertEqual({item["review_status"] for item in sample}, {"pending"})
        for family in {item["family"] for item in sample}:
            self.assertEqual(len({item["template_id"] for item in sample if item["family"] == family}), 10)
        second_reviewer = select_second_reviewer_sample(sample)
        self.assertEqual(len(second_reviewer), 70)
        self.assertEqual(
            Counter(item["family"] for item in second_reviewer),
            {f"F{i}": 10 for i in range(1, 8)},
        )

    def test_post_freeze_challenge_is_balanced_and_separate(self) -> None:
        challenge = generate_challenge_dataset("d1d13cd3822a00b8c5cbd64d3a5ff90552c0159b")
        summary = validate_dataset(challenge, expected_count=210)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["split_counts"], {"challenge": 210})
        self.assertEqual(summary["template_count"], 35)
        self.assertEqual(
            summary["target_counts"],
            {"approved_external_ai": 70, "high_risk_external_ai": 70, "local_private": 70},
        )
        main_template_ids = {case["template_id"] for case in generate_dataset(1)}
        self.assertTrue(main_template_ids.isdisjoint({case["template_id"] for case in challenge}))

    def test_egress_challenge_is_balanced_and_targets_filter_only_gaps(self) -> None:
        first = generate_egress_challenge_dataset()
        second = generate_egress_challenge_dataset()
        summary = validate_dataset(first, expected_count=36)
        self.assertEqual(_digest(first), _digest(second))
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["template_count"], 6)
        self.assertEqual(
            summary["target_counts"],
            {
                "approved_external_ai": 12,
                "high_risk_external_ai": 12,
                "local_private": 12,
            },
        )
        self.assertTrue(any("```" in case["input_request"] for case in first))
        self.assertTrue(any("business_sensitive" in case["risk_classes"] for case in first))

    def test_adversarial_taxonomy_does_not_treat_every_sensitive_case_as_attack(self) -> None:
        cases = generate_dataset(1)
        by_attack = {case["attack_family"]: case for case in cases}
        self.assertEqual(by_attack["plain_api_key"]["case_type"], "routine_sensitive")
        self.assertFalse(by_attack["plain_api_key"]["is_adversarial"])
        self.assertEqual(by_attack["unclear_task"]["case_type"], "benign_stress")
        self.assertFalse(by_attack["unclear_task"]["is_adversarial"])
        self.assertEqual(by_attack["url_encoded_secret"]["case_type"], "adversarial_evasion")
        self.assertTrue(by_attack["url_encoded_secret"]["is_adversarial"])
        self.assertEqual(by_attack["bypass_policy"]["case_type"], "prompt_injection")
        self.assertTrue(by_attack["bypass_policy"]["is_adversarial"])

    def test_review_regeneration_preserves_human_annotations(self) -> None:
        path = self.tmp / "review.csv"
        case = generate_dataset(1)[0]
        generator._write_review_csv(path, [case])
        with path.open("r", encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        row.update(
            {
                "review_status": "approved",
                "reviewer_route": case["expected_route"],
                "reviewer_utility": case["expected_utility"],
                "reviewer_notes": "Reviewed independently.",
            }
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=generator.REVIEW_FIELDNAMES)
            writer.writeheader()
            writer.writerow(row)
        regenerated = generator._write_review_csv(path, [case])
        self.assertEqual(regenerated[0]["review_status"], "approved")
        self.assertEqual(regenerated[0]["reviewer_notes"], "Reviewed independently.")

    def test_repeated_evaluation_is_deterministic_except_latency(self) -> None:
        cases = generate_dataset(2)[:12]
        first = evaluate_cases(cases, self.tmp / "first", "determinism-check")
        second = evaluate_cases(cases, self.tmp / "second", "determinism-check")
        self.assertEqual(_without_latency(first), _without_latency(second))

    def test_evaluation_separates_controller_and_detector_performance(self) -> None:
        cases = generate_dataset(2)[:12]
        report = evaluate_cases(cases, self.tmp / "separation", "separation-check")
        self.assertIn("controller_only_policy_conformance", report)
        self.assertIn("end_to_end_policy_conformance", report)
        self.assertIn("evidence_detection", report)
        self.assertIn("osaurus_style_filter_only", report["baseline_comparison"])
        self.assertIn("osaurus_style_filter_only", report["baseline_definitions"])
        self.assertEqual(
            report["baseline_comparison"]["always_local"]["target_policy_violation_rate"],
            0.0,
        )
        self.assertGreater(
            report["baseline_comparison"]["no_gateway"]["target_policy_violation_rate"],
            0.0,
        )

    def test_legacy_regression_does_not_report_unlabeled_controller_only_score(self) -> None:
        cases = [
            {
                "case_id": "legacy-1",
                "target_profile": "approved_external_ai",
                "input_request": "Explain public API authentication guidance.",
                "expected_route": "delegate_sanitized_to_external_ai",
                "leakage_oracle": {},
                "controller_only_evaluable": False,
            }
        ]
        report = evaluate_cases(cases, self.tmp / "legacy", "legacy-check")
        self.assertIsNone(report["controller_only_policy_conformance"])
        self.assertIsNone(report["by_split"]["regression"]["controller_only_policy_conformance"])

    def test_target_policy_violation_requires_weaker_external_protection(self) -> None:
        self.assertTrue(
            _is_target_policy_violation(
                "delegate_sanitized_to_external_ai",
                "delegate_pseudocode_to_external_ai",
                True,
            )
        )
        self.assertFalse(
            _is_target_policy_violation(
                "delegate_pseudocode_to_external_ai",
                "delegate_sanitized_to_external_ai",
                True,
            )
        )
        self.assertFalse(
            _is_target_policy_violation(
                "local_summary",
                "delegate_sanitized_to_external_ai",
                True,
            )
        )
        self.assertFalse(
            _is_target_policy_violation(
                "delegate_sanitized_to_external_ai",
                "ask_clarification",
                False,
            )
        )


if __name__ == "__main__":
    unittest.main()
