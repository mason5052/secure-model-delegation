from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from smd_app.app import create_app
from smd_app.engine import default_policy
from smd_app.providers import ProviderError, ProviderRegistry


class LocalDouble:
    def __init__(self, ready=True):
        self.ready = ready
        self.calls = []

    async def start(self):
        pass

    async def stop(self):
        pass

    def catalog(self):
        return [{"id": "qwen3:4b", "name": "Qwen3 4B", "size_gb": 2.5}]

    async def status(self):
        return {"ready": self.ready, "runtime_ready": self.ready, "model": "qwen3:4b", "model_digest": "test-digest"}

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return "A local answer."

    async def install(self, model, emit):
        await emit({"stage": "download", "message": "Downloading a test double.", "completed": 1, "total": 2})
        return await self.status()

    async def select(self, model):
        self.ready = True
        return await self.status()


async def local_engine(messages, policy, destination, chat, provider, emit):
    await emit({"stage": "local_answer", "message": "Generating locally."})
    return {"route": "local_process", "answer": await chat(messages), "rule_ids": ["R1"],
            "reasons": ["Local first"], "transforms": [], "payload": None, "inspection": {}}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def client(self, **kwargs):
        app = create_app(self.data_dir, runtime=kwargs.pop("runtime", LocalDouble()),
                         engine=kwargs.pop("engine", local_engine), **kwargs)
        return TestClient(app, base_url="http://127.0.0.1:6728")

    def authorize(self, client):
        token = client.get("/api/v1/session").json()["token"]
        client.headers["x-smd-token"] = token

    def start_run(self, client, prompt="A synthetic request.", conversation=None, destination="local"):
        conversation = conversation or client.post("/api/v1/conversations").json()["id"]
        response = client.post("/api/v1/runs", json={"conversation_id": conversation, "prompt": prompt, "destination": destination})
        self.assertEqual(response.status_code, 200, response.text)
        run_id = response.json()["id"]
        events = [json.loads(line[6:]) for line in client.get(f"/api/v1/runs/{run_id}/events").text.splitlines() if line.startswith("data: ")]
        return conversation, run_id, events

    def test_local_session_host_origin_and_mutation_token(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/status").status_code, 401)
            self.assertEqual(client.get("/api/v1/session", headers={"host": "attacker.example"}).status_code, 403)
            self.assertEqual(client.get("/api/v1/session", headers={"origin": "https://attacker.example"}).status_code, 403)
            self.assertEqual(client.get("/api/v1/session", headers={"sec-fetch-site": "cross-site"}).status_code, 403)
            client.get("/api/v1/session")
            self.assertEqual(client.post("/api/v1/conversations").status_code, 403)
            self.authorize(client)
            self.assertEqual(client.post("/api/v1/conversations").status_code, 200)
            self.assertIn("frame-ancestors 'none'", client.get("/").headers["content-security-policy"])

    def test_local_model_required_even_when_external_provider_configured(self):
        with self.client(runtime=LocalDouble(False)) as client:
            self.authorize(client)
            client.put("/api/v1/providers/openai", json={"api_key": "synthetic-key-not-valid", "model": "test-model"})
            conversation = client.post("/api/v1/conversations").json()["id"]
            response = client.post("/api/v1/runs", json={"conversation_id": conversation, "prompt": "Hello", "destination": "openai"})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(client.get("/api/v1/activity").json()["runs"], [])

    def test_live_catalog_and_file_details_are_independent_of_selected_model(self):
        class HubDouble:
            async def search(self, query, sort):
                return {"models": [{"id": "example/NewFamily-GGUF", "format": "GGUF", "compatibility": "not_checked"}],
                        "query": query, "sort": sort, "source": "Hugging Face"}
            async def details(self, repo):
                return {"id": repo, "license": "apache-2.0", "variants": [
                    {"model_ref": "hf.co/example/NewFamily-GGUF:model-Q4_K_M.gguf", "installable": True}]}
        with self.client(runtime=LocalDouble(False), hub=HubDouble()) as client:
            self.authorize(client)
            result = client.get("/api/v1/models/catalog", params={"query": "NewFamily", "sort": "downloads"}).json()
            self.assertEqual(result["source"], "Hugging Face")
            self.assertEqual(result["query"], "NewFamily")
            self.assertNotIn("qwen", json.dumps(result).lower())
            detail = client.get("/api/v1/models/details", params={"repo": result["models"][0]["id"]}).json()
            self.assertTrue(detail["variants"][0]["installable"])
            self.assertFalse(client.get("/api/v1/status").json()["runtime"]["ready"])

    def test_whole_conversation_survives_and_default_metadata_has_no_body(self):
        runtime = LocalDouble()
        with self.client(runtime=runtime) as client:
            self.authorize(client)
            sentinel = "SYNTHETIC-BODY-UNIQUE-874653"
            conversation, _, first = self.start_run(client, sentinel)
            self.assertEqual(first[-1]["type"], "completed")
            _, run_id, _ = self.start_run(client, "Continue.", conversation)
            self.assertEqual([message["role"] for message in runtime.calls[-1]], ["user", "assistant", "user"])
            self.assertEqual(runtime.calls[-1][0]["content"], sentinel)
            detail = client.get(f"/api/v1/activity/{run_id}").json()
            self.assertFalse(detail["has_content"])
            self.assertIsNone(detail["content"])
        self.assertNotIn(sentinel.encode(), (self.data_dir / "application.sqlite3").read_bytes())

    def test_opt_in_content_deletion_and_keys_not_persisted(self):
        sentinel = "SYNTHETIC-CONTENT-RETAIN-874655"
        key = "synthetic-api-key-for-test-only"
        with self.client() as client:
            self.authorize(client)
            self.assertEqual(client.put("/api/v1/providers/openai", json={"api_key": key, "model": "test-model"}).status_code, 200)
            status = client.get("/api/v1/status").text
            self.assertNotIn(key, status)
            client.patch("/api/v1/settings", json={"save_content": True})
            _, run_id, _ = self.start_run(client, sentinel)
            self.assertIn(sentinel, client.get(f"/api/v1/activity/{run_id}").text)
            self.assertEqual(client.delete("/api/v1/activity").status_code, 200)
            self.assertEqual(client.get("/api/v1/activity").json()["runs"], [])
        contents = (self.data_dir / "application.sqlite3").read_bytes()
        self.assertNotIn(sentinel.encode(), contents)
        self.assertNotIn(key.encode(), contents)
        with self.client() as client:
            self.authorize(client)
            self.assertFalse(any(entry["configured"] for entry in client.get("/api/v1/status").json()["providers"]))

    def test_policy_draft_review_required_and_failure_preserves_active_version(self):
        async def compiler(text, chat):
            raise ValueError("Unsupported policy clause. Revise it.")
        with self.client(compiler=compiler) as client:
            self.authorize(client)
            original = client.get("/api/v1/status").json()["policy"]["id"]
            result = client.post("/api/v1/policies/compile", json={"text": "Retain data for exactly seven days at the provider."})
            self.assertEqual(result.status_code, 422)
            self.assertEqual(client.get("/api/v1/status").json()["policy"]["id"], original)
            saved = client.get("/api/v1/status").json()["draft"]
            self.assertEqual(saved["text"], "Retain data for exactly seven days at the provider.")
            self.assertTrue(saved["issues"])
            row = client.app.state.store.db.execute("SELECT id FROM policies WHERE active=0").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(client.post(f"/api/v1/policies/{row[0]}/activate").status_code, 422)

    def test_model_download_and_explicit_activation_are_separate(self):
        with self.client(runtime=LocalDouble(False)) as client:
            self.authorize(client)
            job = client.post("/api/v1/models/install", json={"model": "qwen3:4b"}).json()["id"]
            events = client.get(f"/api/v1/jobs/{job}/events").text
            self.assertIn('"stage": "download"', events)
            self.assertIn('"type": "completed"', events)
            self.assertFalse(client.get("/api/v1/status").json()["runtime"]["ready"])
            self.assertTrue(client.post("/api/v1/models/select", json={"model": "qwen3:4b"}).json()["ready"])

    def test_provider_timeout_is_failed_not_completed_or_appended(self):
        async def timeout_engine(messages, policy, destination, chat, provider, emit):
            await provider(destination, [{"role": "user", "content": "Only allowed synthetic content"}])
        class TimeoutProvider(ProviderRegistry):
            async def complete(self, name, messages):
                raise ProviderError("Timeout", code="delivery_unknown", delivery_unknown=True)
        registry = TimeoutProvider()
        registry.configure("openai", "synthetic-key-for-tests", "test-model")
        with self.client(engine=timeout_engine, providers=registry) as client:
            self.authorize(client)
            conversation, run_id, events = self.start_run(client, destination="openai")
            self.assertEqual(events[-1]["type"], "failed")
            detail = client.get(f"/api/v1/activity/{run_id}").json()
            self.assertEqual(detail["status"], "delivery_unknown")
            self.assertEqual(detail["external_attempted"], 1)
            self.assertIsNotNone(detail["outbound_hash"])
            self.assertIsNone(detail["content"])
            _, _, success = self.start_run(client, "Try locally.", conversation)
            self.assertEqual(success[-1]["type"], "failed")

    def test_validation_does_not_echo_key_or_untrusted_fields(self):
        with self.client() as client:
            self.authorize(client)
            sentinel = "SYNTHETIC-KEY-MUST-NOT-BE-ECHOED"
            response = client.put("/api/v1/providers/openai", json={"api_key": sentinel, "model": {}, "extra": sentinel})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(sentinel, response.text)

    def test_cancellation_before_first_task_step_releases_operation_lock(self):
        original = asyncio.create_task
        def cancel_before_start(coroutine, *args, **kwargs):
            task = original(coroutine, *args, **kwargs)
            if getattr(getattr(coroutine, "cr_code", None), "co_name", None) == "work":
                task.cancel()
            return task
        with self.client(runtime=LocalDouble(False)) as client:
            self.authorize(client)
            with patch("smd_app.app.asyncio.create_task", side_effect=cancel_before_start):
                job = client.post("/api/v1/models/install", json={"model": "qwen3:4b"}).json()["id"]
                events = client.get(f"/api/v1/jobs/{job}/events").text
                self.assertIn('"code": "cancelled"', events)
            self.assertFalse(client.get("/api/v1/status").json()["busy"])
            self.assertEqual(client.post("/api/v1/models/install", json={"model": "qwen3:4b"}).status_code, 200)

    def test_disk_error_during_policy_save_releases_operation_lock(self):
        with self.client() as client:
            self.authorize(client)
            with patch.object(client.app.state.store, "add_policy", side_effect=OSError("Disk full")):
                self.assertEqual(client.post("/api/v1/policies/compile", json={"text": "Keep data local."}).status_code, 503)
            self.assertFalse(client.get("/api/v1/status").json()["busy"])


if __name__ == "__main__":
    unittest.main()
