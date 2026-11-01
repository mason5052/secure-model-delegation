from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smd_app.opencode import AgentUnavailable, agent_configuration, isolated_environment, prepare_packaged_support, prepare_workspace_guard
from smd_app.workspace import create_workspace_router, file_hash


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.folder = self.root / "selected"
        self.folder.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def client(self):
        router, service = create_workspace_router(self.data)
        @asynccontextmanager
        async def lifespan(app):
            await service.start()
            yield
            await service.stop()
        app = FastAPI(lifespan=lifespan)
        app.include_router(router)
        self.service = service
        return TestClient(app)

    def project(self, client, save=False):
        response = client.post("/api/v1/workspace/projects", json={
            "name": "Synthetic workspace", "folder": str(self.folder), "save_content": save})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def session(self, client, project):
        return client.post(f"/api/v1/workspace/projects/{project['id']}/sessions", json={"title": "Synthetic task"}).json()

    def get(self, client, path):
        return client.get("/api/v1/workspace/" + path)

    def post(self, client, path, body=None):
        return client.post("/api/v1/workspace/" + path, json={} if body is None else body)

    def wait_job(self, client, job_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = self.get(client, "jobs/" + job_id).json()
            if value["status"] != "running":
                return value
            time.sleep(.01)
        self.fail("The test workspace job did not finish.")

    def approve(self, client, response):
        self.assertEqual(response.status_code, 200, response.text)
        value = self.post(client, f"approvals/{response.json()['approval']['id']}/decision", {"approved": True})
        self.assertEqual(value.status_code, 200, value.text)
        return self.wait_job(client, value.json()["job_id"])

    def test_metadata_persists_but_content_requires_opt_in(self):
        sentinel = "SYNTHETIC-WORKSPACE-CONTENT-41987"
        with self.client() as client:
            project = self.project(client)
            session = self.session(client, project)
            self.post(client, f"sessions/{session['id']}/messages", {"role": "user", "content": sentinel})
            self.assertIn(sentinel, self.get(client, f"sessions/{session['id']}/messages").text)
            client.patch(f"/api/v1/workspace/projects/{project['id']}", json={"tabs": [{"type": "session", "id": session["id"]}]})
        self.assertNotIn(sentinel.encode(), (self.data / "workspace/workspace.sqlite3").read_bytes())
        with self.client() as client:
            self.assertEqual(self.get(client, "projects").json()["projects"][0]["name"], "Synthetic workspace")
            result = self.get(client, f"sessions/{session['id']}/messages").json()
            self.assertEqual(result["messages"], [])
            self.assertTrue(result["previous_content_unavailable"])
            self.post(client, f"sessions/{session['id']}/messages", {"role": "user", "content": "New context after restart"})
            result = self.get(client, f"sessions/{session['id']}/messages").json()
            self.assertTrue(result["previous_content_unavailable"])
            self.assertEqual(self.get(client, f"sessions/{session['id']}").json()["message_count"], 2)

    def test_opt_in_retains_history_forks_and_content_search(self):
        with self.client() as client:
            project = self.project(client, save=True)
            session = self.session(client, project)
            for role, content in (("user", "Synthetic retained search token 791"), ("assistant", "Synthetic answer")):
                self.post(client, f"sessions/{session['id']}/messages", {"role": role, "content": content})
            fork = self.post(client, f"sessions/{session['id']}/fork", {"message_index": 0}).json()
            self.assertEqual(fork["parent_id"], session["id"])
            self.assertEqual(fork["message_count"], 1)
        with self.client() as client:
            found = self.get(client, f"projects/{project['id']}/sessions?query=791").json()["sessions"]
            self.assertEqual(len(found), 2)
            history = self.get(client, f"sessions/{session['id']}/messages").json()
            self.assertTrue(history["content_saved"])
            self.assertEqual(len(history["messages"]), 2)
            client.patch(f"/api/v1/workspace/projects/{project['id']}", json={"save_content": False})
        self.assertNotIn(b"Synthetic retained search token 791", (self.data / "workspace/workspace.sqlite3").read_bytes())

    def test_reject_and_one_shot_approval_never_write_early(self):
        with self.client() as client:
            project = self.project(client)
            response = self.post(client, f"projects/{project['id']}/file", {"path": "draft.txt", "content": "First synthetic draft"})
            self.assertFalse((self.folder / "draft.txt").exists())
            value = response.json()["approval"]
            self.assertIn("First synthetic draft", value["details"]["diff"])
            self.post(client, f"approvals/{value['id']}/decision", {"approved": False})
            self.assertFalse((self.folder / "draft.txt").exists())
            response = self.post(client, f"projects/{project['id']}/file", {"path": "draft.txt", "content": "Approved synthetic draft"})
            approval_id = response.json()["approval"]["id"]
            result = self.approve(client, response)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual((self.folder / "draft.txt").read_text(), "Approved synthetic draft")
            self.assertEqual(self.post(client, f"approvals/{approval_id}/decision", {"approved": True}).status_code, 409)

    def test_stale_file_edit_cannot_overwrite_concurrent_changes(self):
        source = self.folder / "draft.txt"
        source.write_text("Before")
        with self.client() as client:
            project = self.project(client)
            response = self.post(client, f"projects/{project['id']}/file", {"path": "draft.txt", "content": "Proposed"})
            source.write_text("Changed by another editor")
            result = self.approve(client, response)
            self.assertEqual(result["status"], "failed")
            self.assertIn("changed after review", result["events"][-1]["error"])
            self.assertEqual(source.read_text(), "Changed by another editor")

    @unittest.skipUnless(os.name == "posix", "Executable permission bits require POSIX.")
    def test_approved_edit_preserves_executable_permission(self):
        source = self.folder / "synthetic.sh"
        source.write_text("printf before")
        source.chmod(0o755)
        with self.client() as client:
            project = self.project(client)
            result = self.approve(client, self.post(client, f"projects/{project['id']}/file", {
                "path": "synthetic.sh", "content": "printf after"}))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(source.stat().st_mode & 0o777, 0o755)

    def test_path_traversal_symlinks_and_control_folders_are_rejected(self):
        outside = self.root / "outside.txt"
        outside.write_text("Synthetic outside content")
        (self.folder / "escape").symlink_to(self.root, target_is_directory=True)
        with self.client() as client:
            project = self.project(client)
            for path in ("../outside.txt", str(outside), "escape/outside.txt", ".git/config", "..\\outside.txt"):
                result = self.post(client, f"projects/{project['id']}/file", {"path": path, "content": "Never written"})
                self.assertEqual(result.status_code, 403, (path, result.text))
            self.assertEqual(self.get(client, f"projects/{project['id']}/file?path=escape/outside.txt").status_code, 403)
        self.assertEqual(outside.read_text(), "Synthetic outside content")

    def test_selected_folder_deletion_preserves_original_files(self):
        (self.folder / "keep.txt").write_text("Preserve")
        with self.client() as client:
            project = self.project(client)
            response = client.delete(f"/api/v1/workspace/projects/{project['id']}")
            self.assertTrue(response.json()["files_preserved"])
            self.assertEqual((self.folder / "keep.txt").read_text(), "Preserve")

    def test_shell_runs_only_after_approval_and_returns_exit_code(self):
        command = ("echo Synthetic output && echo Synthetic marker>approved.txt" if os.name == "nt"
                   else "printf 'Synthetic output'; printf 'Synthetic marker' > approved.txt")
        with self.client() as client:
            project = self.project(client)
            response = self.post(client, f"projects/{project['id']}/commands", {
                "command": command})
            self.assertFalse((self.folder / "approved.txt").exists())
            result = self.approve(client, response)
            self.assertEqual(result["result"]["exit_code"], 0)
            self.assertIn("Synthetic output", json.dumps(result["events"]))
            expected = "Synthetic marker\n" if os.name == "nt" else "Synthetic marker"
            self.assertEqual((self.folder / "approved.txt").read_text(), expected)

    def test_running_command_can_be_cancelled(self):
        with self.client() as client:
            project = self.project(client)
            response = self.post(client, f"projects/{project['id']}/commands", {"command": "sleep 30"})
            approved = self.post(client, f"approvals/{response.json()['approval']['id']}/decision", {"approved": True})
            job_id = approved.json()["job_id"]
            response = self.post(client, f"jobs/{job_id}/cancel")
            self.assertEqual(response.json()["status"], "cancelled")

    def test_document_create_read_and_targeted_edit(self):
        structures = {
            "docx": {"title": "Synthetic report", "paragraphs": ["First paragraph"], "tables": [[["A", "B"]]]},
            "xlsx": {"sheets": [{"name": "Data", "rows": [["Count", "Total"], [2, "=SUM(A2:A2)"]]}]},
            "pptx": {"slides": [{"title": "Synthetic deck", "body": ["First point"]}]},
            "pdf": {"title": "Synthetic PDF", "paragraphs": ["Readable text"]},
        }
        with self.client() as client:
            project = self.project(client)
            for fmt, structure in structures.items():
                result = self.approve(client, self.post(client, f"projects/{project['id']}/document", {
                    "path": "artifact." + fmt, "format": fmt, "structure": structure}))
                self.assertEqual(result["status"], "completed", result)
                read = self.get(client, f"projects/{project['id']}/document?path=artifact.{fmt}")
                self.assertEqual(read.status_code, 200, read.text)
            response = self.get(client, f"projects/{project['id']}/document?path=artifact.xlsx").json()
            self.assertFalse(response["structure"]["formulas_recalculated"])
            self.assertEqual(response["structure"]["sheets"][0]["rows"][1][1], "=SUM(A2:A2)")
            result = self.approve(client, self.post(client, f"projects/{project['id']}/document", {
                "path": "artifact.xlsx", "format": "xlsx", "base_sha256": response["sha256"],
                "structure": {"operations": [{"type": "cell", "sheet": "Data", "cell": "A2", "value": 9}]}}))
            self.assertEqual(result["status"], "completed")
            value = self.get(client, f"projects/{project['id']}/document?path=artifact.xlsx").json()
            self.assertEqual(value["structure"]["sheets"][0]["rows"][1], [9, "=SUM(A2:A2)"])

    def test_html_download_is_attachment_and_document_preview_is_data(self):
        (self.folder / "page.html").write_text("<script>throw 'never execute'</script>")
        with self.client() as client:
            project = self.project(client)
            response = self.get(client, f"projects/{project['id']}/document?path=page.html")
            self.assertIn("application/json", response.headers["content-type"])
            response = self.get(client, f"projects/{project['id']}/download?path=page.html")
            self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))

    def test_sparse_document_grid_cannot_trigger_unbounded_table_allocation(self):
        with self.client() as client:
            project = self.project(client)
            rows = [[] for _ in range(500)] + [["Synthetic"] * 200]
            response = self.post(client, f"projects/{project['id']}/document", {
                "path": "oversized.docx", "format": "docx", "structure": {"tables": [rows]}})
            self.assertEqual(response.status_code, 413)
            self.assertFalse((self.folder / "oversized.docx").exists())
            self.assertEqual(self.get(client, "approvals").json()["approvals"], [])

    def test_skills_are_explicitly_enabled_and_do_not_execute(self):
        with self.client() as client:
            skill = self.post(client, "skills", {"name": "Synthetic skill", "content": "# Instructions\nUse a table."}).json()
            self.assertFalse(skill["enabled"])
            result = client.patch(f"/api/v1/workspace/skills/{skill['id']}", json={"enabled": True})
            self.assertTrue(result.json()["enabled"])
            self.assertEqual(len(self.get(client, "skills").json()["skills"]), 1)
            client.delete(f"/api/v1/workspace/skills/{skill['id']}")
            self.assertEqual(self.get(client, "skills").json()["skills"], [])

    def test_remote_mcp_is_blocked_before_any_network_request(self):
        with self.client() as client:
            server = self.post(client, "mcp", {"name": "Synthetic remote", "transport": "http",
                "url": "https://example.invalid/mcp", "enabled": True}).json()
            self.assertEqual(server["status"], "blocked_remote")
            with patch("smd_app.workspace.httpx.AsyncClient") as network:
                response = self.post(client, f"mcp/{server['id']}/discover")
                self.assertEqual(response.status_code, 403)
                network.assert_not_called()

    def test_local_mcp_discovery_and_tool_call_require_separate_approval(self):
        program = self.root / "synthetic_mcp.py"
        program.write_text("""import json,sys
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    method=request['method']
    result={'protocolVersion':'2025-03-26','capabilities':{}} if method=='initialize' else {'tools':[{'name':'synthetic_echo','inputSchema':{'type':'object'}}]} if method=='tools/list' else {'content':[{'type':'text','text':request['params']['arguments']['text']}]}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
""")
        with self.client() as client:
            server = self.post(client, "mcp", {"name": "Synthetic local", "transport": "stdio",
                "command": [sys.executable, str(program)], "enabled": True}).json()
            response = self.post(client, f"mcp/{server['id']}/discover")
            self.assertEqual(self.get(client, "mcp").json()["servers"][0]["status"], "not_connected")
            result = self.approve(client, response)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["result"]["tools"][0]["name"], "synthetic_echo")
            result = self.approve(client, self.post(client, f"mcp/{server['id']}/call", {
                "name": "synthetic_echo", "arguments": {"text": "Synthetic tool response"}}))
            self.assertEqual(result["result"]["result"]["content"][0]["text"], "Synthetic tool response")

    def test_agent_private_configuration_prevents_provider_and_project_config_inheritance(self):
        gateway = {"base_url": "http://127.0.0.1:6728/api/v1/gateway/v1", "api_key": "synthetic-internal-token"}
        config = agent_configuration(gateway)
        self.assertEqual(config["enabled_providers"], ["smd"])
        self.assertEqual(config["permission"]["edit"], "ask")
        self.assertEqual(config["permission"]["bash"], "ask")
        self.assertEqual(config["permission"]["external_directory"], "deny")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-never-inherit", "OPENCODE_AUTO_SHARE": "true"}):
            env = isolated_environment(self.root / "isolated", gateway, "synthetic-password")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("OPENCODE_AUTO_SHARE", env)
        self.assertEqual(env["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
        self.assertEqual(env["OPENCODE_DB"], ":memory:")
        with self.assertRaises(AgentUnavailable):
            agent_configuration({"base_url": "https://example.invalid/v1", "api_key": "test"})

    def test_packaged_support_copies_only_dependencies_and_rejects_escaping_links(self):
        support = self.root / "packaged-support"
        (support / "node_modules" / "synthetic").mkdir(parents=True)
        (support / "package.json").write_text(json.dumps({"dependencies": {"@opencode-ai/plugin": "1.19.5"}}))
        (support / "package-lock.json").write_text("{}")
        (support / "node_modules/synthetic/index.js").write_text("export default {}")
        (support / "auth.json").write_text("Synthetic excluded auth file")
        (support / "opencode.json").write_text("Synthetic excluded user config")
        profile = self.root / "private-profile"
        prepare_packaged_support(profile, support)
        copied = profile / "config/opencode"
        self.assertTrue((copied / "node_modules/synthetic/index.js").is_file())
        self.assertFalse((copied / "auth.json").exists())
        self.assertFalse((copied / "opencode.json").exists())
        outside = self.root / "outside-support.js"
        outside.write_text("export default {}")
        (support / "node_modules/unsafe.js").symlink_to(outside)
        with self.assertRaises(AgentUnavailable):
            prepare_packaged_support(self.root / "another-profile", support)

    @unittest.skipUnless(shutil.which("node"), "Node is needed to execute the first-party guard's filesystem regression checks.")
    def test_agent_guard_checks_all_file_tools_and_search_does_not_follow_links(self):
        home = self.root / "guard-profile"
        prepare_workspace_guard(home, self.folder)
        config = home / "config/opencode"
        (config / "package.json").write_text('{"type":"module"}')
        sdk = config / "node_modules/@opencode-ai/plugin"
        sdk.mkdir(parents=True)
        (sdk / "package.json").write_text('{"type":"module","exports":"./index.js"}')
        # The SDK stub preserves tool definitions; the real generated plugin's
        # path checks and search implementations execute against actual files.
        (sdk / "index.js").write_text("const schema=new Proxy(function(){},{get:()=>schema,apply:()=>schema});\n"
                                      "const tool=value=>value;tool.schema=schema;export {tool};")
        (self.folder / "README.txt").write_text("The in-folder verification word is Cedar.")
        outside = self.root / "outside-guard"
        outside.mkdir()
        (outside / "outside-only.txt").write_text("SYNTHETIC-OUTSIDE-BOUNDARY-CONTENT")
        (self.folder / "linked-file.txt").symlink_to(outside / "outside-only.txt")
        (self.folder / "linked-folder").symlink_to(outside, target_is_directory=True)
        driver = config / "verify.mjs"
        driver.write_text("import assert from 'node:assert/strict';\n"
            "import {AethonWorkspace} from './plugins/aethon-workspace.js';\n"
            "const root=" + json.dumps(str(self.folder.resolve())) + ";\n"
            "const outside=" + json.dumps(str(outside.resolve())) + ";\n"
            "const guard=await AethonWorkspace();const before=guard['tool.execute.before'];\n"
            "await before({tool:'read'},{args:{filePath:root+'/README.txt'}});\n"
            "for(const name of ['read','edit','write','multiedit']){\n"
            " await assert.rejects(()=>before({tool:name},{args:{filePath:root+'/linked-file.txt'}}));\n"
            " await assert.rejects(()=>before({tool:name},{args:{filePath:root+'/linked-folder/../README.txt'}}));\n"
            " await assert.rejects(()=>before({tool:name},{args:{filePath:outside+'/outside-only.txt'}}));}\n"
            "for(const name of ['glob','grep','list']){\n"
            " await assert.rejects(()=>before({tool:name},{args:{path:root+'/linked-folder'}}));\n"
            " await assert.rejects(()=>guard.tool[name].execute({path:outside,pattern:'**/*.txt'}));}\n"
            "const paths=await guard.tool.glob.execute({path:root,pattern:'**/*.txt'});\n"
            "assert.ok(paths.includes('README.txt'));assert.ok(!paths.includes('linked-file'));assert.ok(!paths.includes('outside-only'));\n"
            "const matches=await guard.tool.grep.execute({path:root,pattern:'SYNTHETIC-OUTSIDE-BOUNDARY-CONTENT'});\n"
            "assert.ok(!matches.includes('outside-only'));assert.ok(!matches.includes('SYNTHETIC-OUTSIDE-BOUNDARY-CONTENT'));\n"
            "assert.ok((await guard.tool.grep.execute({path:root,pattern:'Cedar'})).includes('README.txt:1:'));\n"
            "const listing=await guard.tool.list.execute({path:root});assert.ok(listing.includes('README.txt'));assert.ok(!listing.includes('linked-'));\n"
            "await assert.rejects(()=>before({tool:'apply_patch'},{args:{patchText:'*** Update File: '+outside+'/outside-only.txt'}}));\n")
        result = subprocess.run([shutil.which("node"), str(driver)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
