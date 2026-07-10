from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


DEFAULT_ORACLE_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "oracle_policy.yaml"


@dataclass(frozen=True)
class BenchmarkOracle:
    version: str
    benchmark: str
    target_profiles: tuple[str, ...]
    span_actions: dict[str, str]
    scenario_routes: dict[str, dict[str, str]]
    route_transformations: dict[str, str]
    route_utility: dict[str, str]
    scenario_target_utility: dict[str, dict[str, str]]

    def expected_route(self, scenario: str, target_profile: str) -> str:
        try:
            return self.scenario_routes[scenario][target_profile]
        except KeyError as exc:
            raise ValueError(f"Oracle has no route for scenario={scenario}, target={target_profile}") from exc


def load_benchmark_oracle(path: Optional[str | Path] = None) -> BenchmarkOracle:
    oracle_path = Path(path or DEFAULT_ORACLE_PATH)
    raw = yaml.safe_load(oracle_path.read_text(encoding="utf-8"))
    required = {
        "version",
        "benchmark",
        "target_profiles",
        "span_actions",
        "scenario_routes",
        "route_transformations",
        "route_utility",
    }
    if not isinstance(raw, dict) or not required <= set(raw):
        raise ValueError(f"Invalid benchmark oracle: {oracle_path}")
    target_profiles = tuple(str(item) for item in raw["target_profiles"])
    scenario_routes = {
        str(scenario): {str(target): str(route) for target, route in routes.items()}
        for scenario, routes in raw["scenario_routes"].items()
    }
    for scenario, routes in scenario_routes.items():
        missing = set(target_profiles) - set(routes)
        if missing:
            raise ValueError(f"Oracle scenario {scenario} is missing targets: {sorted(missing)}")
    return BenchmarkOracle(
        version=str(raw["version"]),
        benchmark=str(raw["benchmark"]),
        target_profiles=target_profiles,
        span_actions={str(key): str(value) for key, value in raw["span_actions"].items()},
        scenario_routes=scenario_routes,
        route_transformations={str(key): str(value) for key, value in raw["route_transformations"].items()},
        route_utility={str(key): str(value) for key, value in raw["route_utility"].items()},
        scenario_target_utility={
            str(scenario): {str(target): str(label) for target, label in values.items()}
            for scenario, values in raw.get("scenario_target_utility", {}).items()
        },
    )


def expected_fields(
    oracle: BenchmarkOracle,
    scenario: str,
    target_profile: str,
    risk_classes: list[str],
) -> dict[str, Any]:
    route = oracle.expected_route(scenario, target_profile)
    return {
        "expected_span_actions": [
            {"class": label, "action": oracle.span_actions[label]}
            for label in risk_classes
            if label in oracle.span_actions
        ],
        "expected_route": route,
        "expected_transformation": oracle.route_transformations[route],
        "expected_utility": oracle.scenario_target_utility.get(scenario, {}).get(
            target_profile,
            oracle.route_utility[route],
        ),
    }
