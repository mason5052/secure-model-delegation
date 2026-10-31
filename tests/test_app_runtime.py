from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from smd_app import runtime


DIGEST = "a" * 64


class RuntimeArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.target = self.folder / "payload"
        self.target.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def _tar(self, name, *, link=None):
        archive = self.folder / "engine.tgz"
        with tarfile.open(archive, "w:gz") as output:
            item = tarfile.TarInfo(name)
            if link is not None:
                item.type = tarfile.SYMTYPE
                item.linkname = link
                output.addfile(item)
            else:
                item.size = 6
                item.mode = 0o4755
                output.addfile(item, io.BytesIO(b"engine"))
        return archive

    def test_tar_traversal_is_rejected(self):
        with self.assertRaises(runtime.RuntimeSetupError):
            runtime._extract_archive(self._tar("../escaped"), self.target)
        self.assertFalse((self.folder / "escaped").exists())

    def test_windows_style_zip_traversal_is_rejected(self):
        archive = self.folder / "engine.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("..\\escaped", "bad")
        with self.assertRaises(runtime.RuntimeSetupError):
            runtime._extract_archive(archive, self.target)
        self.assertFalse((self.folder / "escaped").exists())

    def test_symlink_escape_is_rejected(self):
        with self.assertRaises(runtime.RuntimeSetupError):
            runtime._extract_archive(self._tar("outside", link="../../escaped"), self.target)

    def test_normal_files_are_extracted_without_setuid(self):
        runtime._extract_archive(self._tar("bin/ollama"), self.target)
        binary = self.target / "bin" / "ollama"
        self.assertEqual(binary.read_bytes(), b"engine")
        self.assertEqual(binary.stat().st_mode & 0o6000, 0)

    def test_uncompressed_size_limit_is_enforced(self):
        with patch.object(runtime, "MAX_EXTRACTED_BYTES", 4):
            with self.assertRaises(runtime.RuntimeSetupError):
                runtime._extract_archive(self._tar("engine"), self.target)

    def test_safe_library_symlinks_are_preserved(self):
        archive = self.folder / "engine.tgz"
        with tarfile.open(archive, "w:gz") as output:
            item = tarfile.TarInfo("lib/libexample.so.1")
            item.size = 3
            output.addfile(item, io.BytesIO(b"lib"))
            link = tarfile.TarInfo("lib/libexample.so")
            link.type, link.linkname = tarfile.SYMTYPE, "libexample.so.1"
            output.addfile(link)
        runtime._extract_archive(archive, self.target)
        self.assertEqual((self.target / "lib/libexample.so").read_bytes(), b"lib")


class ManagedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.manager = runtime.ManagedRuntime(self.folder)

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temporary.cleanup()

    def _transport(self, handler):
        original = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        return patch.object(runtime.httpx, "AsyncClient", side_effect=lambda *args, **kwargs: original(*args, transport=transport, **kwargs))

    def test_model_references_cannot_choose_urls_paths_or_cloud(self):
        for model in ["qwen3:cloud", "qwen3:4b-cloud", "qwen3:4b:CLOUD", "http://evil/model:4b", "evil.example/model/name:4b", "evil.example/model:4b", "localhost/model:4b", "../model:4b", "qwen3", "model:4b;whoami", "C:\\model:4b"]:
            with self.subTest(model=model), self.assertRaises(runtime.RuntimeSetupError):
                runtime._model_name(model)
        self.assertEqual(runtime._model_name("example/small-model:Q4_K_M"), "example/small-model:Q4_K_M")

    def test_native_hugging_face_references_allow_only_documented_host_and_safe_tags(self):
        for model in ["hf.co/author/Model-GGUF", "hf.co/author/Model-GGUF:Q4_K_M", "hf.co/author/Model-GGUF:Model-Q4_K_M.gguf"]:
            self.assertEqual(runtime._model_name(model), model)
        for model in ["https://hf.co/author/model:Q4", "other.example/author/model:Q4", "hf.co/author/model:cloud", "hf.co/author/model:q4-cloud", "hf.co/author/model:../file.gguf", "hf.co/author/model:sub/file.gguf", "hf.co/author/model/extra", "hf.co/author/model:filename.gguf?token=hidden"]:
            with self.subTest(model=model), self.assertRaises(runtime.RuntimeSetupError):
                runtime._model_name(model)

    def test_child_environment_forces_local_and_disables_body_logging(self):
        self.manager._port = 24567
        with patch.dict(os.environ, {"OLLAMA_NO_CLOUD": "0", "OLLAMA_HOST": "remote.example:80", "OLLAMA_DEBUG_LOG_REQUESTS": "1", "OPENAI_API_KEY": "synthetic-hidden-key"}):
            environment = self.manager._environment()
        self.assertEqual(environment["OLLAMA_NO_CLOUD"], "1")
        self.assertEqual(environment["OLLAMA_HOST"], "127.0.0.1:24567")
        self.assertEqual(environment["OLLAMA_DEBUG_LOG_REQUESTS"], "0")
        self.assertEqual(environment["OLLAMA_MODELS"], str(self.folder.resolve() / "models"))
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(environment.get("HOME"), os.environ.get("HOME"))

    async def test_bad_download_hash_prevents_installation(self):
        self.manager.platform = "linux-amd64"
        received = []
        with self._transport(lambda request: httpx.Response(200, content=b"corrupted engine")):
            with self.assertRaisesRegex(runtime.RuntimeSetupError, "SHA256"):
                await self.manager._install_runtime(AsyncMock(side_effect=lambda event: received.append(event)))
        self.assertFalse(self.manager._runtime_dir.exists())
        self.assertTrue(any(event["stage"] == "runtime_download" for event in received))

    async def test_approved_download_emits_byte_progress(self):
        content = b"verified engine fixture"
        self.manager.platform = "linux-amd64"
        events = []
        assets = {"linux-amd64": ("engine.tgz", hashlib.sha256(content).hexdigest())}
        with patch.object(runtime, "ASSETS", assets), self._transport(lambda request: httpx.Response(200, content=content)):
            await self.manager._download(self.folder / "engine.tgz", AsyncMock(side_effect=lambda event: events.append(event)))
        self.assertEqual(events[-1]["stage"], "runtime_verify")
        self.assertEqual(events[-1]["completed"], len(content))

    async def test_untrusted_redirect_is_not_followed(self):
        requests = []
        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://unapproved.example/engine"})
        with self._transport(handler), self.assertRaisesRegex(runtime.RuntimeSetupError, "approved source"):
            await self.manager._download(self.folder / "engine.tgz", AsyncMock())
        self.assertEqual(len(requests), 1)

    async def test_remote_model_is_rejected_before_any_chat(self):
        self.manager._request = AsyncMock(return_value={"remote_host": "https://remote.example", "capabilities": ["completion"]})
        with self.assertRaisesRegex(runtime.RuntimeSetupError, "remote engine"):
            await self.manager._verify_model("qwen3:4b", smoke=True)
        self.assertEqual(self.manager._request.await_count, 1)

    async def test_newer_model_runtime_requirement_is_rejected(self):
        self.manager._request = AsyncMock(return_value={"requires": "99.0.0", "capabilities": ["completion"]})
        with self.assertRaisesRegex(runtime.RuntimeSetupError, "newer engine"):
            await self.manager._verify_model("qwen3:4b", smoke=True)

    async def test_model_check_checks_chat_and_structured_output(self):
        self.manager._request = AsyncMock(side_effect=[
            {"capabilities": ["completion"], "thinking": {"values": [True, False]}},
            {"models": [{"name": "qwen3:4b", "digest": DIGEST}]},
            {"message": {"content": "OK"}, "done": True},
            {"message": {"content": '{"ok": true}'}, "done": True},
        ])
        self.assertEqual(await self.manager._verify_model("qwen3:4b", smoke=True), DIGEST)
        chat_payload = self.manager._request.await_args_list[-1].kwargs["json"]
        self.assertEqual(chat_payload["think"], False)
        self.assertEqual(chat_payload["format"]["type"], "object")

    async def test_qwen3_without_thinking_control_metadata_disables_thinking(self):
        self.manager._request = AsyncMock(side_effect=[
            {"capabilities": ["completion", "thinking"], "details": {"family": "qwen3"}},
            {"models": [{"name": "qwen3:4b", "digest": DIGEST}]},
            {"message": {"content": "OK"}, "done": True},
            {"message": {"content": '{"ok": true}'}, "done": True},
        ])
        await self.manager._verify_model("qwen3:4b", smoke=True)
        for call in self.manager._request.await_args_list[2:]:
            self.assertIs(call.kwargs["json"]["think"], False)
            self.assertEqual(call.kwargs["json"]["options"]["num_predict"], 256)

    async def test_explicit_always_on_thinking_controls_are_respected(self):
        self.manager._request = AsyncMock(side_effect=[
            {"capabilities": ["completion", "thinking"], "thinking": {"values": ["low", "high"]}},
            {"models": [{"name": "example/reasoner:small", "digest": DIGEST}]},
            {"message": {"content": "OK"}, "done": True},
            {"message": {"content": '{"ok": true}'}, "done": True},
        ])
        await self.manager._verify_model("example/reasoner:small", smoke=True)
        self.assertNotIn("think", self.manager._request.await_args_list[-1].kwargs["json"])

    async def test_qwen3_true_only_metadata_still_uses_verified_false_switch(self):
        self.manager._request = AsyncMock(side_effect=[
            {"capabilities": ["completion", "tools", "thinking"], "details": {"family": "qwen3"}, "thinking": {"values": [True], "default": True}},
            {"models": [{"name": "qwen3:4b", "digest": DIGEST}]},
            {"message": {"thinking": "Separate reasoning is never displayed.", "content": "Reasoning prefix.\n</think>\n\nOK"}, "done": True},
            {"message": {"content": '{"ok": true}'}, "done": True},
        ])
        await self.manager._verify_model("qwen3:4b", smoke=True)
        for call in self.manager._request.await_args_list[2:]:
            self.assertIs(call.kwargs["json"]["think"], False)

    async def test_qwen3_reasoning_prefix_is_not_returned_as_answer(self):
        self.manager._request = AsyncMock(return_value={"message": {"thinking": "Separate reasoning", "content": "Reasoning prefix.\n</think>\n\nFinal answer."}, "done": True})
        answer = await self.manager._chat_model("qwen3:4b", [{"role": "user", "content": "A synthetic smoke request."}], schema=None, temperature=0, max_tokens=256)
        self.assertEqual(answer, "Final answer.")

    async def test_unfinished_thinking_or_missing_final_answer_is_rejected(self):
        for content in ["<think>unfinished reasoning", "<think>reasoning</think>\n"]:
            with self.subTest(content=content):
                self.manager._request = AsyncMock(return_value={"message": {"content": content}, "done": True})
                with self.assertRaises(runtime.RuntimeSetupError):
                    await self.manager._chat_model("qwen3:4b", [{"role": "user", "content": "A synthetic smoke request."}], schema=None, temperature=0, max_tokens=256)

    async def test_literal_closing_tag_in_answer_is_preserved(self):
        for content in ['{"quoted": "</think>"}', "The literal closing tag is </think> in this example."]:
            with self.subTest(content=content):
                self.manager._request = AsyncMock(return_value={"message": {"content": content}, "done": True})
                answer = await self.manager._chat_model("qwen3:4b", [{"role": "user", "content": "A synthetic smoke request."}], schema=None, temperature=0, max_tokens=256)
                self.assertEqual(answer, content)

    async def test_qwen3_family_alias_strips_the_same_reasoning_prefix(self):
        self.manager._request = AsyncMock(side_effect=[
            {"capabilities": ["completion", "thinking"], "details": {"family": "qwen3"}, "thinking": {"values": [True]}},
            {"models": [{"name": "example/custom:small", "digest": DIGEST}]},
            {"message": {"content": "Synthetic reasoning.\n</think>\nOK"}, "done": True},
            {"message": {"content": '{"ok": true}'}, "done": True},
        ])
        await self.manager._verify_model("example/custom:small", smoke=True)
        self.assertIn("example/custom:small", self.manager._qwen_models)
        self.assertIs(self.manager._request.await_args_list[2].kwargs["json"]["think"], False)

    async def test_pull_progress_requires_success_and_preserves_layer_digest(self):
        self.manager._port = 24567
        events = []
        data = '\n'.join(json.dumps(event) for event in [
            {"status": "pulling manifest"},
            {"status": "pulling layer", "digest": "sha256:" + DIGEST, "total": 100, "completed": 60},
            {"status": "verifying sha256 digest"},
            {"status": "success"},
        ])
        with self._transport(lambda request: httpx.Response(200, text=data)):
            await self.manager._pull("qwen3:4b", AsyncMock(side_effect=lambda event: events.append(event)))
        self.assertEqual(events[1]["completed"], 60)
        self.assertEqual(events[1]["digest"], "sha256:" + DIGEST)
        self.assertEqual(events[2]["stage"], "model_verify")
        with self._transport(lambda request: httpx.Response(200, text='{"status":"pulling manifest"}')):
            with self.assertRaisesRegex(runtime.RuntimeSetupError, "before completion"):
                await self.manager._pull("qwen3:4b", AsyncMock())

    async def test_selection_and_digest_survive_new_manager(self):
        self.manager._start_process = AsyncMock()
        self.manager._verify_model = AsyncMock(return_value=DIGEST)
        self.manager._runtime_ready = AsyncMock(return_value=True)
        self.manager._request = AsyncMock(return_value={"models": [{"name": "qwen3:4b", "digest": DIGEST}]})
        selected = await self.manager.select("qwen3:4b")
        self.assertTrue(selected["ready"])
        restored = runtime.ManagedRuntime(self.folder)
        self.assertEqual(restored._model, "qwen3:4b")
        self.assertEqual(restored._digest, DIGEST)
        self.assertFalse(restored._verified)
        restored._runtime_installed = lambda: True
        restored._start_process = AsyncMock()
        restored._verify_model = AsyncMock(return_value=DIGEST)
        await restored.start()
        self.assertTrue(restored._verified)

    async def test_status_rechecks_process_health(self):
        self.manager._model, self.manager._verified = "qwen3:4b", True
        self.manager._process = SimpleNamespace(returncode=1)
        state = await self.manager.status()
        self.assertFalse(state["ready"])
        self.assertFalse(state["runtime_ready"])

    async def test_chat_context_limit_never_drops_history(self):
        self.manager._model, self.manager._verified = "qwen3:4b", True
        self.manager._runtime_ready = AsyncMock(return_value=True)
        self.manager._request = AsyncMock()
        with self.assertRaisesRegex(runtime.RuntimeSetupError, "history was not truncated"):
            await self.manager.chat([{"role": "user", "content": "private text " * 1000}])
        self.manager._request.assert_not_awaited()

    async def test_setup_cancellation_stops_owned_runtime(self):
        began = asyncio.Event()
        async def blocked_setup(emit):
            began.set()
            await asyncio.Event().wait()
        self.manager._install_runtime = blocked_setup
        self.manager._stop_process = AsyncMock()
        with patch.object(runtime.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            task = asyncio.create_task(self.manager.install("qwen3:4b", AsyncMock()))
            await began.wait()
            await self.manager.stop()
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.manager._install_task)
        self.assertIn("canceled", self.manager._error)
        self.assertGreaterEqual(self.manager._stop_process.await_count, 1)

    async def test_download_checks_model_without_selecting_it(self):
        self.manager._install_runtime = AsyncMock()
        self.manager._start_process = AsyncMock()
        self.manager._pull = AsyncMock()
        self.manager._runtime_ready = AsyncMock(return_value=True)
        self.manager._request = AsyncMock(return_value={"models": [{"name": "qwen3:4b", "digest": DIGEST}]})
        async def checked(model, smoke):
            self.manager._installed_models = [model]
            return DIGEST
        self.manager._verify_model = AsyncMock(side_effect=checked)
        with patch.object(runtime.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            result = await self.manager.install("qwen3:4b", AsyncMock())
        self.assertFalse(result["ready"])
        self.assertIsNone(result["model"])
        self.assertEqual(result["downloaded_model"], "qwen3:4b")
        restored = runtime.ManagedRuntime(self.folder)
        self.assertIsNone(restored._model)
        self.assertIn("qwen3:4b", restored._installed_models)

    async def test_downloading_second_model_preserves_active_selection(self):
        self.manager._model, self.manager._digest, self.manager._verified = "qwen3:1.7b", DIGEST, True
        self.manager._install_runtime = AsyncMock()
        self.manager._start_process = AsyncMock()
        self.manager._pull = AsyncMock()
        self.manager._verify_model = AsyncMock(return_value="b" * 64)
        self.manager._runtime_ready = AsyncMock(return_value=True)
        self.manager._request = AsyncMock(return_value={"models": [{"name": "qwen3:1.7b"}, {"name": "qwen3:4b"}]})
        with patch.object(runtime.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            result = await self.manager.install("qwen3:4b", AsyncMock())
        self.assertTrue(result["ready"])
        self.assertEqual(result["model"], "qwen3:1.7b")
        self.assertEqual(result["model_digest"], DIGEST)

    async def test_hf_install_preflight_rejects_gated_or_ambiguous_files(self):
        details = {"gated": True, "private": False, "variants": []}
        with patch.object(runtime.HubCatalog, "details", AsyncMock(return_value=details)):
            with self.assertRaisesRegex(runtime.RuntimeSetupError, "public ungated"):
                await self.manager._hf_download_size("hf.co/example/Model-GGUF:Q4_K_M")
        details = {"gated": False, "private": False, "variants": [{"installable": True, "filename": name, "quantization": "Q4_K_M", "size_bytes": 100} for name in ("A-Q4_K_M.gguf", "B-Q4_K_M.gguf")]}
        with patch.object(runtime.HubCatalog, "details", AsyncMock(return_value=details)):
            with self.assertRaisesRegex(runtime.RuntimeSetupError, "one supported GGUF"):
                await self.manager._hf_download_size("hf.co/example/Model-GGUF:Q4_K_M")
            self.assertEqual(await self.manager._hf_download_size("hf.co/example/Model-GGUF:A-Q4_K_M.gguf"), 100)

    async def test_updating_selected_model_requires_explicit_use_again(self):
        self.manager._model, self.manager._digest, self.manager._verified = "qwen3:4b", DIGEST, True
        self.manager._install_runtime = AsyncMock()
        self.manager._start_process = AsyncMock()
        self.manager._pull = AsyncMock()
        self.manager._verify_model = AsyncMock(return_value="b" * 64)
        self.manager._runtime_ready = AsyncMock(return_value=True)
        self.manager._request = AsyncMock(return_value={"models": [{"name": "qwen3:4b"}]})
        with patch.object(runtime.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            result = await self.manager.install("qwen3:4b", AsyncMock())
        self.assertFalse(result["ready"])
        self.assertEqual(result["model"], "qwen3:4b")
        self.assertIsNone(result["model_digest"])

    async def test_removing_normalized_hf_name_clears_active_selection(self):
        original = "hf.co/example/Small-GGUF:Small-Q4_K_M.gguf"
        self.manager._model, self.manager._digest, self.manager._verified = original, DIGEST, True
        self.manager._installed_models = [original.lower()]
        self.manager._start_process = AsyncMock()
        self.manager._request = AsyncMock(return_value={"status": "success"})
        await self.manager.remove(original.lower())
        self.assertIsNone(self.manager._model)
        self.assertIsNone(self.manager._digest)
        self.assertFalse(self.manager._verified)
        self.assertEqual(self.manager._installed_models, [])

    async def test_start_without_runtime_does_not_download(self):
        self.manager._download = AsyncMock()
        await self.manager.start()
        self.manager._download.assert_not_awaited()
        self.assertFalse((await self.manager.status())["ready"])


if __name__ == "__main__":
    unittest.main()
