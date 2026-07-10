from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smd_gateway.policy_config import load_policy_config


WEIGHT_PROFILES = {
    "balanced": {
        "task_adequacy": 0.45,
        "information_retention": 0.25,
        "model_capability_fit": 0.20,
        "operational_cost": 0.10,
    },
    "task_heavy": {
        "task_adequacy": 0.60,
        "information_retention": 0.15,
        "model_capability_fit": 0.20,
        "operational_cost": 0.05,
    },
    "retention_heavy": {
        "task_adequacy": 0.35,
        "information_retention": 0.40,
        "model_capability_fit": 0.20,
        "operational_cost": 0.05,
    },
    "capability_heavy": {
        "task_adequacy": 0.35,
        "information_retention": 0.20,
        "model_capability_fit": 0.40,
        "operational_cost": 0.05,
    },
    "cost_sensitive": {
        "task_adequacy": 0.40,
        "information_retention": 0.20,
        "model_capability_fit": 0.15,
        "operational_cost": 0.25,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-score allowed routes under alternate utility weights.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def evaluate_sensitivity(report: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy_config()
    rows = report.get("results", [])
    output: dict[str, Any] = {}
    for profile_name, weights in WEIGHT_PROFILES.items():
        correct = 0
        changed = 0
        evaluated = 0
        route_counts: dict[str, int] = {}
        for row in rows:
            scores = row.get("route_utility_scores", {})
            if scores:
                evaluated += 1
                selected = max(
                    scores,
                    key=lambda route: (
                        _score(scores[route], weights),
                        policy.route_preference[route],
                        route,
                    ),
                )
            else:
                selected = str(row["actual_route"])
            correct += selected == row["expected_route"]
            changed += selected != row["actual_route"]
            route_counts[selected] = route_counts.get(selected, 0) + 1
        output[profile_name] = {
            "weights": weights,
            "case_count": len(rows),
            "utility_scored_case_count": evaluated,
            "policy_conformance": 0.0 if not rows else round(correct / len(rows), 6),
            "route_changes_from_balanced": changed,
            "route_distribution": dict(sorted(route_counts.items())),
            "safety_note": "All compared routes were already inside the hard-policy allowed set.",
        }
    return {
        "benchmark": report.get("benchmark"),
        "profiles": output,
    }


def _score(components: dict[str, Any], weights: dict[str, float]) -> float:
    return (
        weights["task_adequacy"] * float(components["task_adequacy"])
        + weights["information_retention"] * float(components["information_retention"])
        + weights["model_capability_fit"] * float(components["model_capability_fit"])
        - weights["operational_cost"] * float(components["operational_cost"])
    )


def main() -> None:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = evaluate_sensitivity(report)
    content = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
