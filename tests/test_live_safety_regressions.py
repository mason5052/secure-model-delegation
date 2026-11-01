"""Controlled protocol regressions, separate from empirical model evaluation."""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from smd_app.agent_gateway import AgentGateway, validate_envelope
from smd_app.engine import DEFAULT_POLICY_TEXT, default_policy, execute
from smd_app.providers import ProviderRegistry
from smd_app.store import Store


class AdvisoryRuntime:
    """A controlled proposal tests enforcement without claiming model accuracy."""

    def __init__(self, fail=False):
        self.fail = fail
        self.inputs = []

    async def status(self):
        return {"ready": True, "model": "controlled-proposal"}

    async def chat(self, messages, **kwargs):
        self.inputs.append(copy.deepcopy(messages))
        if kwargs.get("schema"):
            if self.fail:
                return "not JSON"
            return json.dumps({"uncertain": False, "reason": "Controlled proposal",
                               "findings": [], "local_feasibility": "insufficient"})
        return "Controlled local answer"

    async def agent_complete(self, body):
        self.inputs.append(copy.deepcopy(body))
        return {"choices": [{"message": {"role": "assistant", "content": "Local"}, "finish_reason": "stop"}]}


class LiveSafetyRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name))
        self.store.add_policy(DEFAULT_POLICY_TEXT, default_policy(), True)
        self.received = []

        def receive(request):
            self.received.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": "Controlled receiver answer"}, "finish_reason": "stop"}]})

        self.providers = ProviderRegistry(transport=httpx.MockTransport(receive))
        self.providers.configure("remote", "synthetic-key-only", "controlled-model", base_url="http://127.0.0.1:39999/v1")

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_native_tool_result_and_prior_turn_are_checked_together(self):
        body = {"model": "smd-remote", "messages": [
            {"role": "user", "content": "Public project codeword is Marigold. Contact mila@example.test."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "read-1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "read-1", "content": "Search/attachment extract: api_key=SYNTHETIC-SECRET-2718. Public count is 43."},
            {"role": "user", "content": "Use the public project codeword and count."},
        ]}
        original = copy.deepcopy(body)
        runtime = AdvisoryRuntime()
        gateway = AgentGateway(runtime, self.providers, self.store, "private-test")
        await gateway.complete(body)
        self.assertEqual(body, original)
        self.assertEqual(len(self.received), 1)
        wire = json.dumps(self.received[0])
        for protected in ("mila@example.test", "SYNTHETIC-SECRET-2718"):
            self.assertNotIn(protected, wire)
            self.assertIn(protected, json.dumps(runtime.inputs[0]))
        self.assertIn("Marigold", wire)
        self.assertIn("43", wire)
        self.assertEqual(self.received[0]["messages"][2]["tool_call_id"], "read-1")
        self.assertEqual(self.received[0], gateway.records[-1]["payload"])

    async def test_policy_restriction_overrides_risky_model_proposal(self):
        policy = default_policy()
        for rule in policy["rules"]:
            if rule["action"] == "allow":
                rule["targets"].remove("remote")
        clause = "Keep all requests local for the restricted recipient."
        policy["source_text"] += "\n" + clause
        policy["rules"].append({"id": "R8", "source_text": clause, "targets": ["remote"], "info": ["any"], "action": "local_only"})
        self.store.add_policy(policy["source_text"], policy, True)
        await AgentGateway(AdvisoryRuntime(), self.providers, self.store, "private-test").complete({"model": "smd-remote", "messages": [{"role": "user", "content": "Explain the public word Marigold."}]})
        self.assertEqual(self.received, [])

    async def test_failed_inspection_does_not_dispatch(self):
        await AgentGateway(AdvisoryRuntime(fail=True), self.providers, self.store, "private-test").complete({"model": "smd-remote", "messages": [{"role": "user", "content": "An attached document is unavailable."}]})
        self.assertEqual(self.received, [])

    async def test_input_cannot_select_endpoint_or_model(self):
        invalid = [
            {"model": "https://example.invalid/steal", "messages": [{"role": "user", "content": "Hello"}]},
            {"model": "smd-remote", "base_url": "https://example.invalid/steal", "messages": [{"role": "user", "content": "Hello"}]},
            {"model": "smd-remote", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/private.png"}}]}]},
        ]
        for body in invalid:
            with self.subTest(body=body["model"]), self.assertRaises(ValueError):
                validate_envelope(body)
        self.assertEqual(self.received, [])

    async def test_oversized_complete_envelope_is_rejected_without_truncation(self):
        body = {"model": "smd-remote", "messages": [{"role": "user", "content": "x" * (2 * 1024**2)}]}
        with self.assertRaisesRegex(ValueError, "not truncated"):
            validate_envelope(body)
        self.assertEqual(self.received, [])

    async def test_provider_failure_is_not_retried(self):
        count = 0

        def reject(request):
            nonlocal count
            count += 1
            return httpx.Response(503)

        self.providers._transport = httpx.MockTransport(reject)
        with self.assertRaises(RuntimeError):
            await AgentGateway(AdvisoryRuntime(), self.providers, self.store, "private-test").complete({"model": "smd-remote", "messages": [{"role": "user", "content": "Explain public arithmetic."}]})
        self.assertEqual(count, 1)

    async def test_cancellation_during_inspection_makes_no_provider_call(self):
        entered = asyncio.Event()

        async def inspect(messages, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def emit(event):
            pass

        task = asyncio.create_task(execute([{"role": "user", "content": "Explain public arithmetic."}], default_policy(), "remote", inspect, self.providers.complete, emit))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main()
