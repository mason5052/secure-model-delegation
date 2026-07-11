from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .leakage import evaluate_leakage


@dataclass(frozen=True)
class EgressValidation:
    allowed: bool
    payload_sha256: str
    payload_bytes: int
    direct_findings: list[str]
    canonicalized_findings: list[str]
    structural_code_findings: list[str]

    @property
    def findings(self) -> list[str]:
        return sorted(
            set(
                self.direct_findings
                + self.canonicalized_findings
                + self.structural_code_findings
            )
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "status": "allowed" if self.allowed else "blocked",
            "payload_sha256": self.payload_sha256,
            "payload_bytes": self.payload_bytes,
            "finding_count": len(self.findings),
        }


class EgressGuardViolation(RuntimeError):
    def __init__(self, validation: EgressValidation) -> None:
        self.validation = validation
        super().__init__(
            "Egress guard blocked a transformed payload that still contained "
            f"{len(validation.findings)} protected finding(s)."
        )


def validate_egress_payload(payload: str, leakage_oracle: Any) -> EgressValidation:
    encoded = payload.encode("utf-8")
    leakage = evaluate_leakage(payload, leakage_oracle)
    findings = sorted(
        set(leakage["direct"] + leakage["canonicalized"] + leakage["structural_code"])
    )
    return EgressValidation(
        allowed=not findings,
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
        payload_bytes=len(encoded),
        direct_findings=leakage["direct"],
        canonicalized_findings=leakage["canonicalized"],
        structural_code_findings=leakage["structural_code"],
    )


def enforce_egress_payload(payload: str, leakage_oracle: Any) -> EgressValidation:
    validation = validate_egress_payload(payload, leakage_oracle)
    if not validation.allowed:
        raise EgressGuardViolation(validation)
    return validation
