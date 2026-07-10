from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SourceChunk:
    source: str
    text: str


@dataclass(frozen=True)
class RequestBundle:
    case_id: str
    user_prompt: str
    target_profile: str = "external_ai"
    transport: str = "simulated_external_endpoint"
    retrieved_context: list[SourceChunk] = field(default_factory=list)
    logs: list[SourceChunk] = field(default_factory=list)
    conversation_turns: list[SourceChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedRequest:
    case_id: str
    target_profile: str
    transport: str
    text: str
    current_text: str
    sources: list[str]
    conversation_turns: list[SourceChunk]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SensitiveSpan:
    start: int
    end: int
    text: str
    label: str
    detector: str
    policy_action: str
    severity: str = "medium"
    provider_group: str = "all_detectors"


@dataclass(frozen=True)
class PolicyDecision:
    route: str
    target_profile: Optional[str]
    transport: str
    hard_action: str
    utility_label: str
    reasons: list[str]
    rule_ids: list[str] = field(default_factory=list)
    advisory_route: Optional[str] = None
    candidate_routes: list[str] = field(default_factory=list)
    eliminated_routes: list[dict[str, str]] = field(default_factory=list)
    span_actions: list[dict[str, Any]] = field(default_factory=list)
    conflict_rule_id: Optional[str] = None
    conflict_priority: Optional[int] = None
    transformation_type: str = "none"
    policy_version: str = "unknown"
    utility_assessment: dict[str, Any] = field(default_factory=dict)
    route_utility_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_trace: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GatewayResult:
    case_id: str
    route: str
    hard_action: str
    utility_label: str
    target_profile: Optional[str]
    transport: str
    detected_labels: list[str]
    detected_spans: list[dict[str, Any]]
    decision_reasons: list[str]
    rule_ids: list[str]
    advisory_route: Optional[str]
    delegated_payload: Optional[str]
    sanitized_or_delegated_payload: Optional[str]
    leakage_found: list[str]
    audit_ref: str
    external_ref: Optional[str]
    external_endpoint_payload_ref: Optional[str]
    candidate_routes: list[str] = field(default_factory=list)
    eliminated_routes: list[dict[str, str]] = field(default_factory=list)
    span_actions: list[dict[str, Any]] = field(default_factory=list)
    conflict_rule_id: Optional[str] = None
    conflict_priority: Optional[int] = None
    transformation_type: str = "none"
    policy_version: str = "unknown"
    utility_assessment: dict[str, Any] = field(default_factory=dict)
    route_utility_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_trace: list[str] = field(default_factory=list)
    direct_leakage_found: list[str] = field(default_factory=list)
    canonicalized_leakage_found: list[str] = field(default_factory=list)
    structural_code_leakage_found: list[str] = field(default_factory=list)
