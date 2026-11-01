import json
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from smd_app.agent_gateway import AgentGateway, anthropic_body, validate_envelope
from smd_app.app import create_app
from smd_app.engine import default_policy, DEFAULT_POLICY_TEXT
from smd_app.providers import ProviderRegistry
from smd_app.store import Store, digest


class Local:
    def __init__(self):
        self.calls = []

    async def status(self):
        return {"ready": True, "model": "test-local", "models": []}

    async def start(self):
        pass

    async def stop(self):
        pass

    async def chat(self, messages, **kwargs):
        return json.dumps({"uncertain": False, "reason": "Checked", "findings": [], "local_feasibility": "insufficient"})

    async def agent_complete(self, body):
        self.calls.append(body)
        return {"id": "chatcmpl-test", "object": "chat.completion", "created": 1, "choices": [{"index": 0, "message": {"role": "assistant", "content": "Local answer"}, "finish_reason": "stop"}]}


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.store.add_policy(DEFAULT_POLICY_TEXT, default_policy(), True)
        self.local = Local()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def test_entire_local_agent_protocol_is_preserved(self):
        gateway = AgentGateway(self.local, ProviderRegistry(), self.store, "private")
        body = {"model": "smd-local", "messages": [
            {"role": "system", "content": "Use selected project only."},
            {"role": "user", "content": "Read the test file"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call1", "content": "Synthetic output"},
        ], "tools": [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]}
        await gateway.complete(body)
        self.assertEqual(self.local.calls[0], body)

    async def test_mock_receiver_matches_audit_and_earlier_secret_is_removed(self):
        received = []
        def transport(request):
            received.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "chatcmpl-receiver", "choices": [{"message": {"role": "assistant", "content": "Done"}, "finish_reason": "stop"}]})
        registry = ProviderRegistry(transport=httpx.MockTransport(transport))
        registry.configure("openai", "test-key-12345", "test-model")
        gateway = AgentGateway(self.local, registry, self.store, "private")
        body = {"model": "smd-openai", "messages": [{"role": "user", "content": "Contact alice@example.test."}, {"role": "assistant", "content": "Noted."}, {"role": "user", "content": "Explain this task."}]}
        await gateway.complete(body)
        self.assertEqual(len(received), 1)
        self.assertNotIn("alice@example.test", json.dumps(received))
        self.assertEqual(received[0], gateway.records[-1]["payload"])
        self.assertEqual(digest(received[0]), gateway.records[-1]["outbound_hash"])
        self.assertFalse(received[0]["store"])
        self.assertEqual(len(self.store.activity()), 1)
        self.assertFalse(self.store.activity()[0]["has_content"])

    async def test_local_policy_denial_does_not_generate(self):
        p = default_policy()
        p["rules"] = [{"id": "deny", "source_text": p["source_text"], "targets": ["local"], "info": ["any"], "action": "deny"}]
        self.store.add_policy(DEFAULT_POLICY_TEXT, p, True)
        result = await AgentGateway(self.local, ProviderRegistry(), self.store, "private").complete({"model": "smd-local", "messages": [{"role": "user", "content": "Hello"}]})
        self.assertIn("blocked", result["choices"][0]["message"]["content"])
        self.assertEqual(self.local.calls, [])

    async def test_remote_image_urls_are_rejected_before_any_model_call(self):
        with self.assertRaises(ValueError):
            validate_envelope({"model": "smd-local", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}]}]})

    async def test_anthropic_tool_ids_are_preserved(self):
        body = {"messages": [{"role": "assistant", "content": None, "tool_calls": [{"id": "stable-id", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}, {"role": "tool", "tool_call_id": "stable-id", "content": "file result"}]}
        result = anthropic_body(body, "test")
        self.assertEqual(result["messages"][0]["content"][0]["id"], "stable-id")
        self.assertEqual(result["messages"][1]["content"][0]["tool_use_id"], "stable-id")


class GatewayAuthenticationTests(unittest.TestCase):
    def test_browser_cookie_cannot_access_private_agent_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(Path(folder), runtime=Local()), base_url="http://127.0.0.1") as client:
                client.get("/api/v1/session")
                result = client.get("/api/v1/gateway/v1/models")
                self.assertEqual(result.status_code, 401)
                activity = client.get("/api/v1/agent/activity")
                self.assertEqual(activity.status_code, 200)


if __name__ == "__main__":
    unittest.main()
