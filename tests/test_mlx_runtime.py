from __future__ import annotations

import base64
import copy
import json
import unittest

from smd_app.mlx_runtime import LocalRuntimes
from smd_app.runtime import RuntimeSetupError


class NativeOllamaDouble:
    def __init__(self, response=None):
        self._verified = True
        self._model = "synthetic-qwen:small"
        self._think = {self._model: False}
        self.requests = []
        self.response = response or {
            "message": {"role": "assistant", "content": "Synthetic final answer"},
            "done_reason": "stop", "prompt_eval_count": 17, "eval_count": 5}

    async def _request(self, method, path, **kwargs):
        self.requests.append((method, path, copy.deepcopy(kwargs["json"])))
        return copy.deepcopy(self.response)


def runtime_with(ollama):
    runtime = LocalRuntimes.__new__(LocalRuntimes)
    runtime.engine = "ollama"
    runtime.ollama = ollama
    return runtime


class NativeAgentAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_large_history_and_tool_ids_survive_native_adapter(self):
        ollama = NativeOllamaDouble()
        runtime = runtime_with(ollama)
        body = {"model": "smd-local", "max_tokens": 600, "messages": [
            {"role": "system", "content": "Synthetic project policy"},
            {"role": "user", "content": "Prior full turn. " * 2500},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "stable-request-id", "type": "function", "function": {
                    "name": "read", "arguments": json.dumps({"filePath": "/synthetic/project/README.txt", "limit": 20})}}]},
            {"role": "tool", "tool_call_id": "stable-request-id", "name": "read", "content": "Synthetic verification word: Cedar"},
            {"role": "user", "content": "Report the word using this whole history."}],
            "tools": [{"type": "function", "function": {"name": "read", "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}}}}]}
        original = copy.deepcopy(body)
        self.assertGreater(len(json.dumps(body).encode()), 32768)
        reply = await runtime.agent_complete(body)
        self.assertEqual(body, original)
        self.assertEqual(len(ollama.requests), 1)
        method, path, actual = ollama.requests[0]
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertEqual(len(actual["messages"]), len(body["messages"]))
        self.assertEqual(actual["messages"][1], body["messages"][1])
        self.assertEqual(actual["messages"][3], body["messages"][3])
        call = actual["messages"][2]["tool_calls"][0]
        self.assertEqual(call["id"], "stable-request-id")
        self.assertEqual(call["function"]["arguments"], {"filePath": "/synthetic/project/README.txt", "limit": 20})
        self.assertEqual(actual["tools"], body["tools"])
        self.assertFalse(actual["truncate"])
        self.assertFalse(actual["stream"])
        self.assertFalse(actual["think"])
        self.assertEqual(actual["options"], {"num_ctx": 32768, "num_predict": 600, "temperature": 0})
        self.assertEqual(reply["choices"][0]["message"]["content"], "Synthetic final answer")
        self.assertEqual(reply["usage"], {"prompt_tokens": 17, "completion_tokens": 5})

    async def test_inline_image_bytes_and_text_reach_native_model_without_fetching(self):
        encoded = base64.b64encode(b"synthetic image bytes for adapter verification").decode()
        ollama = NativeOllamaDouble()
        body = {"model": "smd-local", "messages": [
            {"role": "developer", "content": "Synthetic system instruction"},
            {"role": "user", "content": [
                {"type": "text", "text": "Before image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}},
                {"type": "text", "text": "After image"}]}]}
        await runtime_with(ollama).agent_complete(body)
        sent = ollama.requests[0][2]
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "Synthetic system instruction"})
        self.assertEqual(sent["messages"][1]["images"], [encoded])
        self.assertEqual(base64.b64decode(sent["messages"][1]["images"][0]), b"synthetic image bytes for adapter verification")
        self.assertEqual(sent["messages"][1]["content"], "Before image\nAfter image")

    async def test_native_tool_arguments_return_as_json_and_have_stable_ids(self):
        ollama = NativeOllamaDouble({"message": {
            "role": "assistant", "content": "", "thinking": "Synthetic internal reasoning",
            "tool_calls": [
                {"id": "native-stable-id", "function": {"name": "read", "arguments": {"filePath": "/synthetic/README.txt"}}},
                {"function": {"name": "glob", "arguments": {"pattern": "*.txt"}}}]},
            "done_reason": "stop"})
        reply = await runtime_with(ollama).agent_complete({"model": "smd-local", "messages": [{"role": "user", "content": "Read the synthetic file"}]})
        choice = reply["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertNotIn("thinking", choice["message"])
        calls = choice["message"]["tool_calls"]
        self.assertEqual(calls[0]["id"], "native-stable-id")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"filePath": "/synthetic/README.txt"})
        self.assertTrue(calls[1]["id"].startswith("call_"))
        self.assertEqual(calls[1]["type"], "function")

    async def test_schema_and_token_limit_are_translated_without_silent_truncation(self):
        ollama = NativeOllamaDouble({"message": {"role": "assistant", "content": "{}"}, "done_reason": "length"})
        schema = {"type": "object", "properties": {"allowed": {"type": "boolean"}}}
        body = {"model": "smd-local", "messages": [{"role": "user", "content": "Synthetic schema request"}],
                "max_completion_tokens": 100000, "response_format": {"type": "json_schema", "json_schema": {"schema": schema}}}
        reply = await runtime_with(ollama).agent_complete(body)
        sent = ollama.requests[0][2]
        self.assertEqual(sent["format"], schema)
        self.assertEqual(sent["options"]["num_predict"], 8192)
        self.assertFalse(sent["truncate"])
        self.assertEqual(reply["choices"][0]["finish_reason"], "length")

    async def test_unverified_model_cannot_receive_agent_history(self):
        ollama = NativeOllamaDouble()
        ollama._verified = False
        with self.assertRaises(RuntimeSetupError):
            await runtime_with(ollama).agent_complete({"model": "smd-local", "messages": [{"role": "user", "content": "Synthetic request"}]})
        self.assertEqual(ollama.requests, [])

    async def test_known_qwen_thinking_suffix_returns_only_the_final_answer(self):
        ollama = NativeOllamaDouble({"message": {
            "role": "assistant", "content": "Synthetic private segment\n</think>\nCedar"}, "done_reason": "stop"})
        ollama._model = "qwen3:4b"
        reply = await runtime_with(ollama).agent_complete({"model": "smd-local", "messages": [{"role": "user", "content": "Report the synthetic word"}]})
        self.assertEqual(reply["choices"][0]["message"]["content"], "Cedar")

    async def test_large_structured_inspection_preserves_full_context_and_valid_json(self):
        ollama = NativeOllamaDouble({"message": {"role": "assistant", "content": '{"safe":true}'}, "done_reason": "stop"})
        messages = [{"role": "user", "content": "Full synthetic policy context. " * 1200}]
        schema = {"type": "object", "properties": {"safe": {"type": "boolean"}}, "required": ["safe"]}
        self.assertGreater(len(json.dumps(messages).encode()), 8192)
        text = await runtime_with(ollama).chat(messages, schema=schema, max_tokens=256)
        method, path, actual = ollama.requests[0]
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertEqual(actual["messages"], messages)
        self.assertEqual(actual["format"], schema)
        self.assertFalse(actual["truncate"])
        self.assertFalse(actual["think"])
        self.assertEqual(actual["options"]["num_ctx"], 32768)
        self.assertEqual(json.loads(text), {"safe": True})


if __name__ == "__main__":
    unittest.main()
