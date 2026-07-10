from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from smd_gateway import process_request
from smd_gateway.policy_config import PolicyConfigError, load_policy_config
from smd_gateway.request_model import RequestBundle


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "policy.yaml"


class PolicyConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def _write_policy(self, raw: dict, name: str = "policy.yaml") -> Path:
        path = self.tmp / name
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return path

    def test_current_policy_loads_as_runtime_version(self) -> None:
        policy = load_policy_config(POLICY_PATH)
        self.assertEqual(policy.version, "0.3")
        self.assertEqual(policy.canonical_target("external_ai"), "approved_external_ai")

    def test_invalid_action_is_rejected(self) -> None:
        self.raw["sensitive_classes"]["api_key"]["default_span_action"] = "erase"
        with self.assertRaises(PolicyConfigError):
            load_policy_config(self._write_policy(self.raw))

    def test_invalid_route_is_rejected(self) -> None:
        self.raw["sensitive_classes"]["api_key"]["allowed_routes"].append("unknown_route")
        with self.assertRaises(PolicyConfigError):
            load_policy_config(self._write_policy(self.raw))

    def test_invalid_target_profile_is_rejected(self) -> None:
        self.raw["conflict_resolution"]["rules"][0]["target_profiles"] = ["unknown_target"]
        with self.assertRaises(PolicyConfigError):
            load_policy_config(self._write_policy(self.raw))

    def test_missing_detector_class_is_rejected_at_load_time(self) -> None:
        del self.raw["sensitive_classes"]["api_key"]
        with self.assertRaises(PolicyConfigError):
            load_policy_config(self._write_policy(self.raw))

    def test_yaml_conflict_change_changes_runtime_route(self) -> None:
        prompt = "Review this code: function privateHandler(user){ return user.isAdmin === true; }"
        baseline = process_request(
            RequestBundle(
                case_id="POLICY_DEFAULT",
                user_prompt=prompt,
                target_profile="approved_external_ai",
            ),
            run_dir=self.tmp / "default",
        )
        self.assertEqual(baseline.route, "delegate_pseudocode_to_external_ai")

        for rule in self.raw["conflict_resolution"]["rules"]:
            if rule["id"] == "source_code_target_profile_matrix":
                rule["force_route"] = "local_summary"
                break
        changed_path = self._write_policy(self.raw, "changed-policy.yaml")
        changed = process_request(
            RequestBundle(
                case_id="POLICY_CHANGED",
                user_prompt=prompt,
                target_profile="approved_external_ai",
            ),
            run_dir=self.tmp / "changed",
            policy_path=changed_path,
        )
        self.assertEqual(changed.route, "local_summary")
        self.assertEqual(changed.conflict_rule_id, "source_code_target_profile_matrix")


if __name__ == "__main__":
    unittest.main()
