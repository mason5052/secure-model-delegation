from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


REQUIRED_ROUTES = {
    "local_process",
    "deny_request",
    "ask_clarification",
    "local_summary",
    "delegate_sanitized_to_external_ai",
    "delegate_pseudocode_to_external_ai",
}
REQUIRED_ACTIONS = {
    "allow",
    "remove",
    "replace_with_placeholder",
    "generalize",
    "summarize_locally",
    "deny_span",
}
REQUIRED_SENSITIVE_CLASSES = {
    "api_key",
    "auth_token",
    "config_secret",
    "pii_name",
    "pii_email",
    "pii_phone",
    "internal_hostname",
    "private_ip",
    "internal_infrastructure",
    "source_code",
    "proprietary_code",
    "incident_detail",
    "system_prompt",
    "prompt_injection",
}
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "configs" / "policy.yaml"


class PolicyConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SensitiveClassPolicy:
    label: str
    severity: str
    default_span_action: str
    placeholder: str
    raw_external_delegation: bool
    allowed_routes: frozenset[str]
    escalates_with: frozenset[str]
    target_policy: dict[str, str] = field(default_factory=dict)
    leakage_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetProfilePolicy:
    name: str
    trust_level: str
    aliases: tuple[str, ...]
    source_code_policy: str


@dataclass(frozen=True)
class ConflictRule:
    rule_id: str
    priority: int
    force_route: Optional[str]
    when_all_labels: frozenset[str]
    when_any_labels: frozenset[str]
    when_any_companion_labels: frozenset[str]
    when_request_flags: frozenset[str]
    target_profiles: frozenset[str]
    effect: str


@dataclass(frozen=True)
class PolicyConfig:
    version: str
    project: str
    span_actions: frozenset[str]
    route_labels: frozenset[str]
    utility_labels: frozenset[str]
    target_profiles: dict[str, TargetProfilePolicy]
    sensitive_classes: dict[str, SensitiveClassPolicy]
    conflict_rules: tuple[ConflictRule, ...]
    route_preference: dict[str, int]
    leakage_oracle_defaults: dict[str, Any]
    target_aliases: dict[str, str]
    source_path: Path

    def canonical_target(self, target: str) -> str:
        canonical = self.target_aliases.get(target, target)
        if canonical not in self.target_profiles:
            raise PolicyConfigError(f"Unknown target profile: {target}")
        return canonical

    def class_policy(self, label: str) -> SensitiveClassPolicy:
        try:
            return self.sensitive_classes[label]
        except KeyError as exc:
            raise PolicyConfigError(f"No policy is defined for evidence label: {label}") from exc


def load_policy_config(path: Optional[Path | str] = None) -> PolicyConfig:
    policy_path = Path(path or DEFAULT_POLICY_PATH).resolve()
    if not policy_path.is_file():
        raise PolicyConfigError(f"Policy file does not exist: {policy_path}")
    return _load_policy_cached(str(policy_path), policy_path.stat().st_mtime_ns)


@lru_cache(maxsize=16)
def _load_policy_cached(path: str, _mtime_ns: int) -> PolicyConfig:
    policy_path = Path(path)
    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyConfigError(f"Unable to load policy file {policy_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyConfigError("Policy root must be a YAML mapping")
    return _parse_policy(raw, policy_path)


def _parse_policy(raw: dict[str, Any], source_path: Path) -> PolicyConfig:
    version = _required_string(raw, "version")
    project = _required_string(raw, "project")
    span_actions = frozenset(_string_list(raw.get("span_actions"), "span_actions"))
    route_labels = frozenset(_string_list(raw.get("route_labels"), "route_labels"))
    utility_labels = frozenset(_string_list(raw.get("utility_labels"), "utility_labels"))

    missing_routes = REQUIRED_ROUTES - route_labels
    if missing_routes:
        raise PolicyConfigError(f"Policy is missing required routes: {sorted(missing_routes)}")
    missing_actions = REQUIRED_ACTIONS - span_actions
    if missing_actions:
        raise PolicyConfigError(f"Policy is missing required span actions: {sorted(missing_actions)}")

    target_profiles_raw = _required_mapping(raw, "target_profiles")
    target_profiles: dict[str, TargetProfilePolicy] = {}
    target_aliases: dict[str, str] = {}
    for name, value in target_profiles_raw.items():
        if not isinstance(value, dict):
            raise PolicyConfigError(f"target_profiles.{name} must be a mapping")
        aliases = tuple(_string_list(value.get("aliases", []), f"target_profiles.{name}.aliases"))
        target_profiles[name] = TargetProfilePolicy(
            name=name,
            trust_level=_required_string(value, "trust_level", f"target_profiles.{name}"),
            aliases=aliases,
            source_code_policy=_required_string(value, "source_code_policy", f"target_profiles.{name}"),
        )
        target_aliases[name] = name
        for alias in aliases:
            if alias in target_aliases and target_aliases[alias] != name:
                raise PolicyConfigError(f"Target alias is assigned more than once: {alias}")
            target_aliases[alias] = name

    sensitive_raw = _required_mapping(raw, "sensitive_classes")
    missing_classes = REQUIRED_SENSITIVE_CLASSES - set(sensitive_raw)
    if missing_classes:
        raise PolicyConfigError(
            f"Policy is missing required sensitive classes: {sorted(missing_classes)}"
        )
    sensitive_classes: dict[str, SensitiveClassPolicy] = {}
    for label, value in sensitive_raw.items():
        if not isinstance(value, dict):
            raise PolicyConfigError(f"sensitive_classes.{label} must be a mapping")
        action = _required_string(value, "default_span_action", f"sensitive_classes.{label}")
        if action not in span_actions:
            raise PolicyConfigError(f"Invalid action for {label}: {action}")
        allowed_routes = frozenset(
            _string_list(value.get("allowed_routes"), f"sensitive_classes.{label}.allowed_routes")
        )
        invalid_routes = allowed_routes - route_labels
        if invalid_routes:
            raise PolicyConfigError(f"Invalid routes for {label}: {sorted(invalid_routes)}")
        target_policy = value.get("target_policy", {})
        if not isinstance(target_policy, dict):
            raise PolicyConfigError(f"sensitive_classes.{label}.target_policy must be a mapping")
        sensitive_classes[label] = SensitiveClassPolicy(
            label=label,
            severity=_required_string(value, "severity", f"sensitive_classes.{label}"),
            default_span_action=action,
            placeholder=str(value.get("placeholder", "")),
            raw_external_delegation=bool(value.get("raw_external_delegation", False)),
            allowed_routes=allowed_routes,
            escalates_with=frozenset(
                _string_list(value.get("escalates_with", []), f"sensitive_classes.{label}.escalates_with")
            ),
            target_policy={str(key): str(item) for key, item in target_policy.items()},
            leakage_patterns=tuple(
                _string_list(value.get("leakage_patterns", []), f"sensitive_classes.{label}.leakage_patterns")
            ),
        )

    conflict_raw = raw.get("conflict_resolution", {})
    if not isinstance(conflict_raw, dict):
        raise PolicyConfigError("conflict_resolution must be a mapping")
    rules_raw = conflict_raw.get("rules", [])
    if not isinstance(rules_raw, list):
        raise PolicyConfigError("conflict_resolution.rules must be a list")
    conflict_rules: list[ConflictRule] = []
    seen_rule_ids: set[str] = set()
    for index, value in enumerate(rules_raw):
        if not isinstance(value, dict):
            raise PolicyConfigError(f"conflict_resolution.rules[{index}] must be a mapping")
        rule_id = _required_string(value, "id", f"conflict_resolution.rules[{index}]")
        if rule_id in seen_rule_ids:
            raise PolicyConfigError(f"Duplicate conflict rule ID: {rule_id}")
        seen_rule_ids.add(rule_id)
        force_route = value.get("force_route")
        if force_route is not None and str(force_route) not in route_labels:
            raise PolicyConfigError(f"Invalid force_route for {rule_id}: {force_route}")
        target_names = frozenset(
            _string_list(value.get("target_profiles", []), f"conflict_resolution.rules.{rule_id}.target_profiles")
        )
        invalid_targets = target_names - set(target_profiles)
        if invalid_targets:
            raise PolicyConfigError(f"Invalid target profiles for {rule_id}: {sorted(invalid_targets)}")
        conflict_rules.append(
            ConflictRule(
                rule_id=rule_id,
                priority=int(value.get("priority", 0)),
                force_route=None if force_route is None else str(force_route),
                when_all_labels=frozenset(_string_list(value.get("when_all_labels", []), rule_id)),
                when_any_labels=frozenset(_string_list(value.get("when_any_labels", []), rule_id)),
                when_any_companion_labels=frozenset(
                    _string_list(value.get("when_any_companion_labels", []), rule_id)
                ),
                when_request_flags=frozenset(_string_list(value.get("when_request_flags", []), rule_id)),
                target_profiles=target_names,
                effect=str(value.get("effect", "")),
            )
        )
    conflict_rules.sort(key=lambda item: (-item.priority, item.rule_id))

    route_preference_raw = _required_mapping(raw, "route_preference")
    route_preference = {str(key): int(value) for key, value in route_preference_raw.items()}
    if set(route_preference) != set(route_labels):
        missing = route_labels - set(route_preference)
        extra = set(route_preference) - route_labels
        raise PolicyConfigError(
            f"route_preference must cover every route; missing={sorted(missing)}, extra={sorted(extra)}"
        )

    leakage_defaults = raw.get("leakage_oracle_defaults", {})
    if not isinstance(leakage_defaults, dict):
        raise PolicyConfigError("leakage_oracle_defaults must be a mapping")

    return PolicyConfig(
        version=version,
        project=project,
        span_actions=span_actions,
        route_labels=route_labels,
        utility_labels=utility_labels,
        target_profiles=target_profiles,
        sensitive_classes=sensitive_classes,
        conflict_rules=tuple(conflict_rules),
        route_preference=route_preference,
        leakage_oracle_defaults=leakage_defaults,
        target_aliases=target_aliases,
        source_path=source_path,
    )


def _required_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict) or not value:
        raise PolicyConfigError(f"{key} must be a non-empty mapping")
    return value


def _required_string(raw: dict[str, Any], key: str, prefix: str = "policy") -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyConfigError(f"{prefix}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise PolicyConfigError(f"{field_name} must be a list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise PolicyConfigError(f"{field_name} must contain only non-empty strings")
    return [item.strip() for item in value]
