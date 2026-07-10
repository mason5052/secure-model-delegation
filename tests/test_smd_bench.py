from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from smd_bench import generator
from smd_bench.generator import generate_dataset, select_human_review_sample
from smd_bench.schema import validate_dataset
from smd_gateway.evaluation import evaluate_cases


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

    def test_pilot_and_full_schema_validation(self) -> None:
        pilot = generate_dataset(2)
        pilot_summary = validate_dataset(pilot, expected_count=140)
        self.assertTrue(pilot_summary["valid"])
        self.assertEqual(pilot_summary["normalized_duplicate_count"], 0)

        full = generate_dataset(20)
        full_summary = validate_dataset(full, expected_count=1400)
        self.assertTrue(full_summary["valid"])
        self.assertEqual(full_summary["family_counts"], {f"F{index}": 200 for index in range(1, 8)})
        self.assertEqual(
            full_summary["target_counts"],
            {"approved_external_ai": 469, "high_risk_external_ai": 462, "local_private": 469},
        )
        self.assertEqual(full_summary["split_counts"], {"development": 1120, "holdout": 280})
        self.assertTrue(full_summary["template_split_isolation"])

    def test_human_review_sample_is_stratified_and_pending(self) -> None:
        sample = select_human_review_sample(generate_dataset(20))
        self.assertEqual(len(sample), 210)
        self.assertEqual(Counter(item["family"] for item in sample), {f"F{i}": 30 for i in range(1, 8)})
        self.assertEqual(
            Counter(item["target_profile"] for item in sample),
            {"local_private": 70, "approved_external_ai": 70, "high_risk_external_ai": 70},
        )
        self.assertEqual(Counter(item["split"] for item in sample), {"development": 105, "holdout": 105})
        self.assertEqual({item["review_status"] for item in sample}, {"pending"})
        for family in {item["family"] for item in sample}:
            self.assertEqual(len({item["template_id"] for item in sample if item["family"] == family}), 10)

    def test_repeated_evaluation_is_deterministic_except_latency(self) -> None:
        cases = generate_dataset(2)[:12]
        first = evaluate_cases(cases, self.tmp / "first", "determinism-check")
        second = evaluate_cases(cases, self.tmp / "second", "determinism-check")
        self.assertEqual(_without_latency(first), _without_latency(second))


if __name__ == "__main__":
    unittest.main()
