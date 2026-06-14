from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from smd_gateway.web_app import app


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_returns_ok(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_examples_returns_at_least_five_examples(self) -> None:
        response = self.client.get("/api/examples")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 5)

    def test_api_key_process_has_no_raw_key_in_delegated_payload(self) -> None:
        raw_key = "synthetic-service-key-123456"
        response = self.client.post(
            "/api/process",
            json={
                "case_id": "WEB_TEST_API_KEY",
                "user_prompt": f"Debug this 401 API error: SERVICE_KEY={raw_key} returns unauthorized.",
                "target_profile": "external_ai",
                "transport": "simulated_external_endpoint",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["route"], "delegate_sanitized_to_external_ai")
        self.assertNotIn(raw_key, payload["delegated_payload"])
        self.assertEqual(payload["leakage_found"], [])

    def test_source_code_process_uses_pseudocode_or_local_summary(self) -> None:
        response = self.client.post(
            "/api/process",
            json={
                "case_id": "WEB_TEST_CODE",
                "user_prompt": "Review this code: function updateOrder(user){ return order.status = 'paid'; }",
            },
        )
        self.assertEqual(response.status_code, 200)
        route = response.json()["route"]
        self.assertIn(route, {"delegate_pseudocode_to_external_ai", "local_summary"})

    def test_benign_prompt_returns_no_leakage(self) -> None:
        response = self.client.post(
            "/api/process",
            json={
                "case_id": "WEB_TEST_BENIGN",
                "user_prompt": "Explain OWASP LLM Top 10 at a high level.",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["leakage_found"], [])


if __name__ == "__main__":
    unittest.main()
