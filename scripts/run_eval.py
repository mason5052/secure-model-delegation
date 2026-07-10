from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smd_gateway.evaluation import add_regression_metadata, evaluate_cases, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Secure Model Delegation datasets.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "benchmark_cases.jsonl")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "runs" / "eval")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--benchmark-name", default="63-case regression set")
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_jsonl(args.dataset)
    if args.dataset.name == "benchmark_cases.jsonl":
        cases = add_regression_metadata(cases, ROOT / "data" / "regression_case_metadata.json")
    report = evaluate_cases(cases, args.run_dir, args.benchmark_name)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    output = report
    if args.summary_only:
        output = {key: value for key, value in report.items() if key not in {"results", "by_family_target"}}
    print(json.dumps(output, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
