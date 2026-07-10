from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIMARY = ROOT / "data" / "review" / "smd_bench_1400_human_review_sample.csv"
DEFAULT_SECONDARY = ROOT / "data" / "review" / "smd_bench_1400_second_reviewer_sample.csv"
UTILITY_ORDER = {"insufficient": 0, "partial": 1, "sufficient": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize SMD-Bench human review agreement.")
    parser.add_argument("--primary", type=Path, default=DEFAULT_PRIMARY)
    parser.add_argument("--secondary", type=Path, default=DEFAULT_SECONDARY)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def summarize(primary: dict[str, dict[str, str]], secondary: dict[str, dict[str, str]]) -> dict:
    overlap = sorted(set(primary) & set(secondary))
    route_pairs = [
        (primary[case_id]["reviewer_route"].strip(), secondary[case_id]["reviewer_route"].strip())
        for case_id in overlap
        if primary[case_id]["reviewer_route"].strip()
        and secondary[case_id]["reviewer_route"].strip()
    ]
    utility_pairs = [
        (primary[case_id]["reviewer_utility"].strip(), secondary[case_id]["reviewer_utility"].strip())
        for case_id in overlap
        if primary[case_id]["reviewer_utility"].strip()
        and secondary[case_id]["reviewer_utility"].strip()
    ]
    return {
        "overlap_count": len(overlap),
        "completed_route_pairs": len(route_pairs),
        "route_raw_agreement": _raw_agreement(route_pairs),
        "route_cohen_kappa": _cohen_kappa(route_pairs),
        "completed_utility_pairs": len(utility_pairs),
        "utility_raw_agreement": _raw_agreement(utility_pairs),
        "utility_weighted_cohen_kappa": _weighted_kappa(utility_pairs),
        "status": "complete" if len(route_pairs) == len(overlap) else "pending",
    }


def _raw_agreement(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    return round(sum(left == right for left, right in pairs) / len(pairs), 6)


def _cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    labels = sorted({item for pair in pairs for item in pair})
    left = Counter(pair[0] for pair in pairs)
    right = Counter(pair[1] for pair in pairs)
    observed = sum(a == b for a, b in pairs) / len(pairs)
    expected = sum((left[label] / len(pairs)) * (right[label] / len(pairs)) for label in labels)
    if expected == 1.0:
        return 1.0
    return round((observed - expected) / (1.0 - expected), 6)


def _weighted_kappa(pairs: list[tuple[str, str]]) -> float | None:
    valid = [pair for pair in pairs if pair[0] in UTILITY_ORDER and pair[1] in UTILITY_ORDER]
    if not valid:
        return None
    categories = len(UTILITY_ORDER)
    max_distance = float((categories - 1) ** 2)
    observed_disagreement = sum(
        (UTILITY_ORDER[left] - UTILITY_ORDER[right]) ** 2 / max_distance
        for left, right in valid
    ) / len(valid)
    left_counts = Counter(UTILITY_ORDER[left] for left, _ in valid)
    right_counts = Counter(UTILITY_ORDER[right] for _, right in valid)
    expected_disagreement = 0.0
    for left in range(categories):
        for right in range(categories):
            weight = (left - right) ** 2 / max_distance
            expected_disagreement += (
                weight
                * left_counts[left]
                / len(valid)
                * right_counts[right]
                / len(valid)
            )
    if expected_disagreement == 0.0:
        return 1.0
    return round(1.0 - observed_disagreement / expected_disagreement, 6)


def main() -> None:
    args = parse_args()
    report = summarize(load_rows(args.primary), load_rows(args.secondary))
    content = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
