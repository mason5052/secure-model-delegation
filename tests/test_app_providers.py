from __future__ import annotations

import json
import unittest

import httpx

from smd_app.providers import ProviderError, ProviderRegistry


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_uses_official_responses_and_disables_storage(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Public answer."}]}]})

        registry = ProviderRegistry(transport=httpx.MockTransport(handler))
        registry.configure("openai", "test-private-key-1234", "gpt-test")
        answer = await registry.complete("openai", [{"role": "user", "content": "Public question."}])
        self.assertEqual(answer, "Public answer.")
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/responses")
        self.assertFalse(json.loads(requests[0].content)["store"])
        status = registry.status()[0]
        self.assertEqual(status["masked_key"], "********1234")
        self.assertNotIn("test-private", json.dumps(registry.status()))
        registry.remove("openai")
        self.assertFalse(registry.configured("openai"))

    async def test_anthropic_splits_system_and_keeps_all_turns(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]})

        registry = ProviderRegistry(transport=httpx.MockTransport(handler))
        registry.configure("anthropic", "test-private-key-1234", "claude-test")
        messages = [{"role": "system", "content": "Fixed instruction."}, {"role": "user", "content": "First."}, {"role": "assistant", "content": "Second."}, {"role": "user", "content": "Third."}]
        self.assertEqual(await registry.complete("anthropic", messages), "Done.")
        body = json.loads(requests[0].content)
        self.assertEqual(str(requests[0].url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(body["system"], "Fixed instruction.")
        self.assertEqual(body["messages"], messages[1:])
        self.assertEqual(requests[0].headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("temperature", body)

    async def test_timeout_is_not_retried_and_reports_unknown_delivery(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("sensitive error details", request=request)

        registry = ProviderRegistry(transport=httpx.MockTransport(handler))
        registry.configure("openai", "test-private-key-1234", "gpt-test")
        with self.assertRaises(ProviderError) as caught:
            await registry.complete("openai", [{"role": "user", "content": "Public."}])
        self.assertTrue(caught.exception.delivery_unknown)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("sensitive", str(caught.exception))

    async def test_provider_errors_do_not_expose_response_body(self):
        registry = ProviderRegistry(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="Private prompt and key value")))
        registry.configure("openai", "test-private-key-1234", "gpt-test")
        with self.assertRaises(ProviderError) as caught:
            await registry.complete("openai", [{"role": "user", "content": "Public."}])
        self.assertEqual(caught.exception.code, "authentication_failed")
        self.assertNotIn("Private", str(caught.exception))

    async def test_provider_missing_and_arbitrary_endpoints_are_rejected(self):
        registry = ProviderRegistry()
        with self.assertRaises(ProviderError):
            await registry.complete("openai", [{"role": "user", "content": "Public."}])
        with self.assertRaises(ValueError):
            registry.configure("custom", "test-private-key-1234", "model")
        with self.assertRaises(ValueError):
            registry.configure("openai", "test-private-key-1234", "https://private.example")

    async def test_incomplete_provider_text_is_not_reported_as_complete(self):
        for name, body in (
            ("openai", {"status": "incomplete", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Partial text"}]}]}),
            ("anthropic", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "Partial text"}]}),
        ):
            registry = ProviderRegistry(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
            registry.configure(name, "test-private-key-1234", "test-model")
            with self.assertRaises(ProviderError) as caught:
                await registry.complete(name, [{"role": "user", "content": "Public."}])
            self.assertEqual(caught.exception.code, "invalid_response")
            self.assertFalse(caught.exception.delivery_unknown)


if __name__ == "__main__":
    unittest.main()
