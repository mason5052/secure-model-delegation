from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from smd_gateway import process_request
from smd_gateway.egress import EgressGuardViolation, enforce_egress_payload
from smd_gateway.egress_sanitizer import restore_local_placeholders, sanitize_egress_with_map
from smd_gateway.request_model import RequestBundle, SensitiveSpan


class EgressHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_repeated_value_uses_stable_placeholder_and_can_restore_locally(self) -> None:
        original = "alex@example.com"
        text = f"Contact {original}, then confirm with {original}."
        first = text.index(original)
        second = text.index(original, first + 1)
        spans = [
            SensitiveSpan(
                start=start,
                end=start + len(original),
                text=original,
                label="pii_email",
                detector="test",
                policy_action="replace_with_placeholder",
            )
            for start in (first, second)
        ]
        result = sanitize_egress_with_map(text, spans)
        self.assertEqual(result.text.count("[EMAIL_1]"), 2)
        self.assertNotIn("[EMAIL_2]", result.text)
        self.assertEqual(
            restore_local_placeholders(result.text, result.placeholder_to_original),
            text,
        )

    def test_egress_guard_fails_closed_on_remaining_protected_text(self) -> None:
        with self.assertRaises(EgressGuardViolation):
            enforce_egress_payload(
                "Forward synthetic-secret-value to the provider.",
                {"must_not_contain": ["synthetic-secret-value"]},
            )

    def test_simulated_endpoint_records_exact_wire_metadata(self) -> None:
        result = process_request(
            RequestBundle(
                case_id="T_WIRE_CAPTURE",
                user_prompt=(
                    "Debug this 401 API issue: "
                    "SERVICE_KEY=synthetic-service-key-654321."
                ),
            ),
            leakage_oracle={"must_not_contain": ["synthetic-service-key-654321"]},
            run_dir=self.tmp,
        )
        records = [
            json.loads(line)
            for line in Path(result.external_ref or "").read_text(encoding="utf-8").splitlines()
        ]
        wire = records[-1]
        self.assertEqual(wire["egress_guard_status"], "allowed")
        self.assertEqual(len(wire["wire_body_sha256"]), 64)
        self.assertGreater(wire["wire_body_bytes"], 0)
        self.assertNotIn("synthetic-service-key-654321", wire["payload"])

    def test_fenced_code_with_secret_never_reaches_external_endpoint(self) -> None:
        result = process_request(
            RequestBundle(
                case_id="T_FENCED_CODE_SECRET",
                target_profile="approved_external_ai",
                user_prompt=(
                    "Review this private snippet:\n```python\n"
                    "SERVICE_KEY=synthetic-service-key-codeblock-123456\n"
                    "def authorize(user): return user.isAdmin\n```"
                ),
            ),
            leakage_oracle={
                "must_not_contain": [
                    "synthetic-service-key-codeblock-123456",
                    "def authorize(user): return user.isAdmin",
                ]
            },
            run_dir=self.tmp,
        )
        self.assertEqual(result.route, "local_summary")
        self.assertIsNone(result.external_ref)

    def test_failed_post_transform_check_escalates_to_local_summary(self) -> None:
        result = process_request(
            RequestBundle(
                case_id="T_EGRESS_ESCALATION",
                target_profile="approved_external_ai",
                user_prompt=(
                    "Review this proprietary code design in the private payment "
                    "module for an authorization bug."
                ),
            ),
            run_dir=self.tmp,
        )
        self.assertEqual(result.route, "local_summary")
        self.assertEqual(result.conflict_rule_id, "egress_guard_fail_closed")
        self.assertIsNone(result.external_ref)
        self.assertIn("local_summary", result.candidate_routes)
        self.assertTrue(
            any(
                item["reason"] == "egress_guard_blocked"
                for item in result.eliminated_routes
            )
        )
        audit = [
            json.loads(line)
            for line in Path(result.audit_ref).read_text(encoding="utf-8").splitlines()
        ][-1]
        self.assertEqual(audit["egress_validation"]["status"], "blocked")
        self.assertEqual(audit["wire_metadata"], {})


if __name__ == "__main__":
    unittest.main()
