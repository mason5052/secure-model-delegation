"""Reproducible, local-only measurements through the application's live adapters.

This module never contacts a paid provider. Its separately running HTTP receiver
executes received synthetic tasks with the same local model. Private outputs
contain complete synthetic inputs and outputs and must not be bulk-published.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import copy
import csv
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .engine import INSPECTION_SCHEMA, _strict_json, _validate_schema, execute, validate_policy
from .mlx_runtime import LocalRuntimes
from .providers import ProviderRegistry
from .runtime import RUNTIME_VERSION


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def read_records(path: Path) -> list[dict]:
    raw = path.read_text()
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("Evaluation identifiers must contain only ASCII letters, digits, underscores and hyphens.")
    return value


def code_manifest() -> dict:
    root = Path(__file__).resolve().parents[2]
    result = {"root": str(root), "files": {}}
    for path in sorted((root / "src" / "smd_app").rglob("*.py")):
        result["files"][str(path.relative_to(root))] = file_hash(path)
    result["source_hash"] = sha256(canonical(result["files"]))
    try:
        result["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        result["git_tree"] = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
        result["working_changes"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        result["git_commit"] = None
    return result


def normalized(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in string_leaves(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in string_leaves(child)]
    return []


def decoded_views(text: str) -> list[str]:
    views = [text, unquote(text)]
    with contextlib.suppress(ValueError):
        views.extend(string_leaves(json.loads(text)))
    for token in re.findall(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{12,}={0,2}(?![A-Za-z0-9+/])", text):
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            views.append(base64.b64decode(token, validate=True).decode("utf-8"))
    for token in re.findall(r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{2}){6,}(?![A-Fa-f0-9])", text):
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            views.append(bytes.fromhex(token).decode("utf-8"))
    return views


def disclosure_check(text: str, fixture: dict) -> dict:
    values = fixture.get("protected_values", [])
    code = fixture.get("protected_code_fragments", [])
    views = decoded_views(text)
    direct_views = [text]
    with contextlib.suppress(ValueError):
        direct_views.extend(string_leaves(json.loads(text)))
    joined = [normalized(x) for x in views]
    return {
        "direct_protected_values": [index for index, value in enumerate(values) if value and any(value in view for view in direct_views)],
        "normalized_or_decoded_values": [index for index, value in enumerate(values) if value and any(normalized(value) in view for view in joined)],
        "protected_code_fragments": [index for index, value in enumerate(code) if value and any(normalized(value) in view for view in joined)],
        "required_context_facts": {str(index): any(normalized(value) in view for view in joined) for index, value in enumerate(fixture.get("required_context_facts", []))},
        "semantic_disclosure": "not_independently_reviewed",
    }


def json_answer(answer: str) -> Any:
    with contextlib.suppress(ValueError):
        return json.loads(answer)
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", answer)
    if fenced:
        with contextlib.suppress(ValueError):
            return json.loads(fenced.group(1))
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", answer):
        with contextlib.suppress(ValueError):
            return decoder.raw_decode(answer[match.start():])[0]
    raise ValueError("The answer contains no decodable JSON object.")


def quality_check(answer: str, fixture: dict) -> dict:
    rubric = fixture.get("quality", {})
    kind = rubric.get("type", "pending_human")
    if kind in {"pending_human", "not_scored"}:
        return {"status": kind, "success": None}
    if kind == "clarification":
        terms = rubric.get("required_any_terms", ["missing", "attach", "upload", "provide"])
        success = any(term.casefold() in answer.casefold() for term in terms)
        success = success and not any(str(value).casefold() in answer.casefold() for value in rubric.get("forbidden_fabricated_values", []))
        return {"status": "automated_lexical_clarification_proxy", "success": success}
    if kind != "json_fields":
        return {"status": "unsupported_rubric", "success": None}
    try:
        parsed = json_answer(answer)
    except ValueError:
        return {"status": "invalid_json", "success": False, "field_results": {}}
    expected = rubric.get("expected", {})
    field_results = {}
    for key, desired in expected.items():
        actual = parsed.get(key) if isinstance(parsed, dict) else None
        if isinstance(desired, str):
            field_results[key] = isinstance(actual, str) and " ".join(actual.casefold().split()) == " ".join(desired.casefold().split())
        elif isinstance(desired, (int, float)) and not isinstance(desired, bool):
            field_results[key] = isinstance(actual, (int, float)) and not isinstance(actual, bool) and abs(actual - desired) < 1e-8
        else:
            field_results[key] = actual == desired
    shape_ok = isinstance(parsed, dict) and (rubric.get("allow_extra_fields", True) or set(parsed) == set(expected))
    return {"status": "automated_predeclared_fields", "success": bool(expected) and shape_ok and all(field_results.values()), "field_results": field_results}


class CallRecorder:
    def __init__(self, runtime: LocalRuntimes, output: Path, prefix: str):
        self.runtime, self.output, self.prefix = runtime, output, prefix
        self.current = "setup"
        self.phase = "setup"
        self.records: list[dict] = []
        self.original = runtime.ollama._request
        runtime.ollama._request = self.request

    async def request(self, method, path, **kwargs):
        if method != "POST" or path != "/api/chat":
            return await self.original(method, path, **kwargs)
        sequence = len(self.records) + 1
        record = {"sequence": sequence, "run_id": self.current, "phase": self.phase, "request": copy.deepcopy(kwargs.get("json")), "started_at": time.time()}
        self.records.append(record)
        started = time.perf_counter()
        try:
            response = await self.original(method, path, **kwargs)
            record["response"] = response
            record["status"] = "completed"
            return response
        except BaseException as exc:
            record["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["seconds"] = time.perf_counter() - started
            write_json(self.output / "model-calls" / f"{self.prefix}-{sequence:05d}.json", record)


class WireTransport(httpx.AsyncBaseTransport):
    """Observe actual serialized bytes, then send them over a real TCP socket."""
    def __init__(self, output: Path, port: int):
        self.output, self.port = output, port
        self.current = "setup"
        self.records: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        parsed = urlsplit(str(request.url))
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != self.port or parsed.path != "/v1/chat/completions":
            raise httpx.ConnectError("The evaluation transport only permits its private loopback receiver.", request=request)
        body = await request.aread()
        name = f"{self.current}-{len(self.records) + 1:04d}"
        path = self.output / "sent-bodies" / (name + ".bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        record = {"run_id": self.current, "body_path": str(path.relative_to(self.output)), "sha256": sha256(body), "bytes": len(body), "endpoint": "private_loopback", "request_headers_saved": False}
        self.records.append(record)
        started = time.perf_counter()
        try:
            async with httpx.AsyncHTTPTransport(retries=0) as transport:
                response = await transport.handle_async_request(request)
                await response.aread()
            record["response_status"] = response.status_code
            record["status"] = "completed"
            return response
        except BaseException as exc:
            record["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["seconds"] = time.perf_counter() - started
            write_json(self.output / "sent-bodies" / (name + ".json"), record)

    async def aclose(self):
        pass


async def receiver_main(config: dict) -> None:
    """Independent process: receive raw bytes before invoking the real adapter."""
    output = Path(config["output"])
    runtime = LocalRuntimes(Path(config["runtime_profile"]))
    runtime.ollama._port = config["runtime_port"]
    runtime.ollama._model = config["model"]
    runtime.ollama._verified = True
    runtime.engine = "ollama"

    async def borrowed_ready():
        try:
            result = await runtime.ollama._request("GET", "/api/version")
            return result.get("version") == RUNTIME_VERSION
        except RuntimeError:
            return False

    runtime.ollama._runtime_ready = borrowed_ready
    await runtime.ollama._verify_model(config["model"], smoke=False)
    recorder = CallRecorder(runtime, output, "receiver")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sequence = 0
    token = config["token"]

    @app.post("/v1/chat/completions")
    async def complete(request: Request):
        nonlocal sequence
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401)
        sequence += 1
        current = sequence
        body = await request.body()
        body_path = output / "received-bodies" / f"receipt-{current:05d}.bin"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        receipt = {"sequence": current, "received_at": time.time(), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "body_path": str(body_path.relative_to(output)), "status": "received", "separate_process_pid": os.getpid()}
        receipt_path = output / "received-bodies" / f"receipt-{current:05d}.json"
        write_json(receipt_path, receipt)
        recorder.current = f"receipt-{current:05d}"
        recorder.phase = "task_answer"
        started = time.perf_counter()
        try:
            data = json.loads(body)
            if set(data) != {"model", "messages", "stream"} or data["model"] != config["model"] or data["stream"] is not False:
                raise ValueError("The controlled receiver accepts only the frozen text request shape.")
            answer = await runtime.chat(data["messages"], temperature=0, max_tokens=2048)
            receipt["status"] = "completed"
            receipt["answer_sha256"] = sha256(answer.encode())
            receipt["answer"] = answer
            model_calls = [x for x in recorder.records if x["run_id"] == recorder.current]
            usage = {"prompt_tokens": sum(x.get("response", {}).get("prompt_eval_count", 0) for x in model_calls), "completion_tokens": sum(x.get("response", {}).get("eval_count", 0) for x in model_calls)}
            receipt["usage"] = usage
            return {"id": f"loopback-{current:05d}", "object": "chat.completion", "created": int(time.time()), "model": config["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}], "usage": usage}
        except BaseException as exc:
            receipt["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            receipt["error_type"] = type(exc).__name__
            raise HTTPException(502, "The local controlled receiver could not complete this synthetic task.") from None
        finally:
            receipt["seconds"] = time.perf_counter() - started
            write_json(receipt_path, receipt)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        port = listener.getsockname()[1]
        print(json.dumps({"port": port, "pid": os.getpid()}), flush=True)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
        await server.serve(sockets=[listener])


def link_tree(source: Path, target: Path) -> None:
    def link_or_copy(src, dst):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    shutil.copytree(source, target, copy_function=link_or_copy)


class EvaluationSession:
    """An owned runtime/receiver pair; no access to the user's running profile."""
    def __init__(self, output: Path, runtime_source: Path, model: str = "qwen3:4b", timeout: float = 240):
        self.output, self.runtime_source, self.model = Path(output), Path(runtime_source), model
        self.timeout = timeout
        self.runtime: LocalRuntimes | None = None
        self.receiver = None
        self.registry = None
        self.transport = None
        self.calls = None
        self.results: list[dict] = []

    async def start(self):
        self.output.mkdir(parents=True, exist_ok=False, mode=0o700)
        profile = self.output / "runtime"
        profile.mkdir(mode=0o700)
        for name in ("runtimes", "models"):
            link_tree(self.runtime_source / name, profile / name)
        write_json(profile / "runtime-state.json", {"version": 1, "runtime_version": RUNTIME_VERSION, "model": self.model, "model_digest": None, "installed_models": [self.model]})
        self.runtime = LocalRuntimes(profile)
        self.calls = CallRecorder(self.runtime, self.output, "parent")
        started = time.perf_counter()
        await self.runtime.start()
        status = await self.runtime.status()
        if not status.get("ready"):
            raise RuntimeError("The isolated local model did not become ready: " + str(status.get("error")))
        show = await self.runtime.ollama._request("POST", "/api/show", json={"model": self.model})
        write_json(self.output / "model-show.json", show)
        model_files = {}
        manifests = list((profile / "models" / "manifests").rglob("*"))
        wanted = None
        for path in manifests:
            if path.is_file() and path.parent.name == self.model.split(":")[0] and path.name == self.model.split(":")[-1]:
                wanted = path
                break
        if wanted:
            manifest = json.loads(wanted.read_text())
            model_files[str(wanted.relative_to(profile))] = {"sha256": file_hash(wanted), "bytes": wanted.stat().st_size}
            for item in [manifest["config"], *manifest["layers"]]:
                path = profile / "models" / "blobs" / item["digest"].replace(":", "-")
                model_files[str(path.relative_to(profile))] = {"sha256": file_hash(path), "declared_digest": item["digest"], "bytes": path.stat().st_size, "media_type": item.get("mediaType")}
        write_json(self.output / "runtime-manifest.json", {"model": self.model, "status": status, "files": model_files, "hardware": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "platform": platform.platform()}, "setup_warmup_seconds": time.perf_counter() - started, "setup_model_calls_excluded": len(self.calls.records), "temperature": 0, "seed": "not_exposed_by_app_adapter", "think": self.runtime.ollama._think.get(self.model), "text_num_ctx": 8192, "large_inspection_num_ctx": 32768, "inspection_output_limit": 4096, "task_output_limit": 2048, "retry_count": 0, "state": "fresh_messages_each_run; no model response reuse; engine may reuse prompt prefix/KV cache", "task_answer_adapter": "smd_app.mlx_runtime.LocalRuntimes.chat", "code": code_manifest()})
        self.receiver = await asyncio.create_subprocess_exec(sys.executable, "-m", "smd_app.evaluation", "--receiver", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        token = secrets.token_urlsafe(32)
        config = {"output": str(self.output), "runtime_profile": str(profile), "runtime_port": self.runtime.ollama._port, "model": self.model, "token": token}
        self.receiver.stdin.write(json.dumps(config).encode() + b"\n")
        await self.receiver.stdin.drain()
        self.receiver.stdin.close()
        ready = json.loads(await asyncio.wait_for(self.receiver.stdout.readline(), 30))
        self.receiver_port = ready["port"]
        self.transport = WireTransport(self.output, self.receiver_port)
        self.registry = ProviderRegistry(transport=self.transport, timeout=self.timeout)
        self.registry.configure("remote", token, self.model, base_url=f"http://127.0.0.1:{self.receiver_port}/v1")
        write_json(self.output / "processes.json", {"owned_runtime_pid": self.runtime.ollama._process.pid, "owned_runtime_port": self.runtime.ollama._port, "receiver_pid": ready["pid"], "receiver_port": self.receiver_port, "token_saved": False})

    async def evaluate_case(self, case: dict, fixture: dict, policy: dict, arm: str) -> dict:
        if arm not in {"A", "B", "C"}:
            raise ValueError("Use arm A, B or C.")
        run_id = safe_id(case["case_id"]) + "-" + arm
        if (self.output / "runs" / (run_id + ".json")).exists():
            raise FileExistsError("A measured run is never silently overwritten or retried.")
        destination = "local" if arm == "A" or case["profile"] == "local" else "remote"
        self.calls.current, self.calls.phase = run_id, "inspection"
        self.transport.current = run_id
        model_start, wire_start = len(self.calls.records), len(self.transport.records)
        receipt_start = len(list((self.output / "received-bodies").glob("*.json"))) if (self.output / "received-bodies").exists() else 0
        events, assessments = [], []
        started = time.perf_counter()
        record = {"run_id": run_id, "case_id": case["case_id"], "task_id": case["task_id"], "group_id": case["group_id"], "profile": case["profile"], "arm": arm, "destination": destination, "messages_sha256": sha256(canonical(case["messages"])), "policy_sha256": sha256(canonical(policy)), "started_at": time.time(), "independent_human_authorization": "pending", "independent_semantic_review": "pending", "external_provider": "none; controlled loopback uses same local model"}

        async def chat(messages, **kwargs):
            if kwargs.get("schema") is not None:
                self.calls.phase = "inspection"
                if arm in {"A", "B"}:
                    assessment = {"uncertain": False, "reason": "Deterministic app-policy baseline; pattern evidence is applied by the engine.", "findings": [], "local_feasibility": "insufficient"}
                    assessments.append({"source": "fixed_deterministic_baseline", "assessment": assessment})
                    return json.dumps(assessment)
                raw = await self.runtime.chat(messages, **kwargs)
                parsed = None
                try:
                    parsed = _strict_json(raw)
                    _validate_schema(parsed, INSPECTION_SCHEMA)
                except ValueError:
                    pass
                assessments.append({"source": "local_model", "raw": raw, "schema_valid": parsed is not None, "assessment": parsed})
                return raw
            self.calls.phase = "task_answer"
            return await self.runtime.chat(messages, **kwargs)

        async def emit(event):
            events.append({"elapsed_seconds": time.perf_counter() - started, **copy.deepcopy(event)})

        try:
            result = await asyncio.wait_for(execute(case["messages"], policy, destination, chat, self.registry.complete if destination != "local" else None, emit), self.timeout)
            record["status"] = "completed"
            record["result"] = result
            record["quality"] = quality_check(result["answer"], fixture)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            record["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "timeout" if isinstance(exc, asyncio.TimeoutError) else "failed"
            record["error_type"] = type(exc).__name__
            record["delivery_unknown"] = bool(getattr(exc, "delivery_unknown", False))
            record["quality"] = {"status": "execution_failure", "success": False}
        record["seconds"] = time.perf_counter() - started
        record["events"] = events
        record["assessments"] = assessments
        if assessments and assessments[-1].get("assessment"):
            assessment = assessments[-1]["assessment"]
            record["advisory_proposal"] = "request_external_help" if assessment.get("local_feasibility") == "insufficient" else "prefer_local" if assessment.get("local_feasibility") == "sufficient" else "uncertain"
        else:
            record["advisory_proposal"] = "unvalidated_or_failed"
        record["parent_model_calls"] = len(self.calls.records) - model_start
        record["wire_requests"] = copy.deepcopy(self.transport.records[wire_start:])
        receipts = sorted((self.output / "received-bodies").glob("*.json"))[receipt_start:] if (self.output / "received-bodies").exists() else []
        record["receipts"] = [json.loads(path.read_text()) for path in receipts]
        observed = record["wire_requests"] or record["receipts"]
        record["wire_receipt_exact_match"] = (len(record["wire_requests"]) == len(record["receipts"]) and all(a["sha256"] == b["sha256"] and a["bytes"] == b["bytes"] for a, b in zip(record["wire_requests"], record["receipts"]))) if observed else None
        for receipt in record["receipts"]:
            text = (self.output / receipt["body_path"]).read_text()
            receipt["fixture_check"] = disclosure_check(text, fixture)
        payload = record.get("result", {}).get("payload")
        sent = record["wire_requests"]
        if payload is not None and sent:
            sent_body = json.loads((self.output / sent[0]["body_path"]).read_bytes())
            record["display_payload_matches_received_messages"] = payload == sent_body.get("messages") and record["wire_receipt_exact_match"]
        else:
            record["display_payload_matches_received_messages"] = None
        parent_calls = self.calls.records[model_start:]
        record["parent_tokens"] = {"prompt": sum(x.get("response", {}).get("prompt_eval_count", 0) for x in parent_calls), "completion": sum(x.get("response", {}).get("eval_count", 0) for x in parent_calls)}
        record["receiver_tokens"] = {"prompt": sum(x.get("usage", {}).get("prompt_tokens", 0) for x in record["receipts"]), "completion": sum(x.get("usage", {}).get("completion_tokens", 0) for x in record["receipts"])}
        record["stage_seconds"] = {phase: sum(x["seconds"] for x in parent_calls if x["phase"] == phase) for phase in ("inspection", "task_answer")}
        record["stage_seconds"]["receiver_task_answer"] = sum(x.get("seconds", 0) for x in record["receipts"])
        record["total_model_calls"] = record["parent_model_calls"] + sum(1 for x in record["receipts"] if x.get("status") in {"completed", "failed"})
        record["paid_cost_usd"] = 0
        self.results.append(record)
        write_json(self.output / "runs" / (run_id + ".json"), record)
        return record

    async def close(self):
        if self.receiver and self.receiver.returncode is None:
            self.receiver.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.receiver.wait(), 10)
            if self.receiver.returncode is None:
                self.receiver.kill()
                await self.receiver.wait()
        if self.runtime:
            await self.runtime.stop()
        if self.output.exists():
            write_json(self.output / "cleanup.json", {"receiver_stopped": not self.receiver or self.receiver.returncode is not None, "owned_model_engine_stopped": self.runtime is None or self.runtime.ollama._process is None, "user_profile_modified": False})


def write_summaries(output: Path, records: list[dict]) -> None:
    rows = []
    for record in records:
        result = record.get("result", {})
        checks = [x.get("fixture_check", {}) for x in record.get("receipts", [])]
        rows.append({"run_id": record["run_id"], "case_id": record["case_id"], "task_id": record["task_id"], "profile": record["profile"], "arm": record["arm"], "status": record["status"], "advisory_proposal": record["advisory_proposal"], "route": result.get("route", "unresolved"), "inspection_reliable": result.get("inspection", {}).get("reliable"), "quality_success": record["quality"].get("success"), "quality_status": record["quality"]["status"], "http_requests": len(record.get("wire_requests", [])), "http_receipts": len(record.get("receipts", [])), "exact_wire_match": record["wire_receipt_exact_match"], "display_matches": record.get("display_payload_matches_received_messages"), "direct_findings": sum(len(x.get("direct_protected_values", [])) for x in checks), "normalized_findings": sum(len(x.get("normalized_or_decoded_values", [])) for x in checks), "code_findings": sum(len(x.get("protected_code_fragments", [])) for x in checks), "missing_context_facts": sum(sum(not value for value in x.get("required_context_facts", {}).values()) for x in checks), "seconds": round(record["seconds"], 6), "inspection_seconds": round(record["stage_seconds"]["inspection"], 6), "local_answer_seconds": round(record["stage_seconds"]["task_answer"], 6), "receiver_answer_seconds": round(record["stage_seconds"]["receiver_task_answer"], 6), "model_calls": record["total_model_calls"], "prompt_tokens": record["parent_tokens"]["prompt"] + record["receiver_tokens"]["prompt"], "completion_tokens": record["parent_tokens"]["completion"] + record["receiver_tokens"]["completion"], "paid_cost_usd": 0, "human_review": "pending"})
    if rows:
        with (output / "case-results.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    aggregate = []
    for arm in ("A", "B", "C"):
        for profile in sorted({row["profile"] for row in rows}):
            group = [row for row in rows if row["arm"] == arm and row["profile"] == profile]
            if not group:
                continue
            completed = sum(row["status"] == "completed" for row in group)
            quality_measured = sum(row["quality_success"] is not None for row in group)
            aggregate.append({"arm": arm, "profile": profile, "runs": len(group), "completed": completed, "quality_measured": quality_measured, "quality_successes": sum(row["quality_success"] is True for row in group), "http_requests": sum(row["http_requests"] for row in group), "http_receipts": sum(row["http_receipts"] for row in group), "direct_findings": sum(row["direct_findings"] for row in group), "normalized_findings": sum(row["normalized_findings"] for row in group), "code_findings": sum(row["code_findings"] for row in group), "missing_context_facts": sum(row["missing_context_facts"] for row in group), "mean_seconds": round(sum(row["seconds"] for row in group) / len(group), 6), "total_model_calls": sum(row["model_calls"] for row in group), "prompt_tokens": sum(row["prompt_tokens"] for row in group), "completion_tokens": sum(row["completion_tokens"] for row in group), "paid_cost_usd": 0})
    if aggregate:
        with (output / "aggregate.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(aggregate[0]))
            writer.writeheader()
            writer.writerows(aggregate)
    write_json(output / "summary.json", {"runs": len(rows), "independent_tasks": len({row["task_id"] for row in rows}), "conditions_per_task": "three recipient profiles; each is repeated across A/B/C", "rows": aggregate, "independent_human_review": "not_performed", "paid_provider_calls": 0})


async def run_main(args):
    cases = read_records(args.dataset)
    fixtures = {item["case_id"]: item for item in read_records(args.fixtures)}
    policies = json.loads(args.policies.read_text())
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique.")
    for case in cases:
        safe_id(case["case_id"])
        if case["profile"] not in {"local", "approved_external", "restricted_external"}:
            raise ValueError("Unknown recipient profile.")
        validate_policy(policies[case["policy_id"]])
        if case["case_id"] not in fixtures:
            raise ValueError("Every case needs a frozen, separately held fixture.")
    freeze = {"created_at": time.time(), "dataset": {"path": str(args.dataset), "sha256": file_hash(args.dataset)}, "fixtures": {"path": str(args.fixtures), "sha256": file_hash(args.fixtures)}, "policies": {"path": str(args.policies), "sha256": file_hash(args.policies)}, "code": code_manifest(), "arms": args.arms, "runs": len(cases) * len(args.arms), "cases": len(cases), "independent_task_groups": len({case["group_id"] for case in cases}), "order": "task/case order from frozen dataset; arms rotated by case index", "repeats": 1, "retry_count": 0, "timeout_seconds": args.timeout, "model": args.model, "human_review": "pending", "quality_rubrics_fixed_before_execution": True}
    session = EvaluationSession(args.output, args.runtime_source, args.model, args.timeout)
    try:
        await session.start()
        write_json(args.output / "execution-freeze.json", freeze)
        print(json.dumps({"state": "ready", "freeze_sha256": file_hash(args.output / "execution-freeze.json"), "output": str(args.output), "runs": freeze["runs"]}), flush=True)
        for index, case in enumerate(cases):
            arms = args.arms[index % len(args.arms):] + args.arms[:index % len(args.arms)]
            for arm in arms:
                record = await session.evaluate_case(case, fixtures[case["case_id"]], policies[case["policy_id"]], arm)
                write_summaries(args.output, session.results)
                print(json.dumps({"completed_runs": len(session.results), "run_id": record["run_id"], "status": record["status"], "route": record.get("result", {}).get("route"), "http_receipts": len(record["receipts"]), "seconds": round(record["seconds"], 3)}), flush=True)
        write_json(args.output / "post-execution-source-check.json", {"before": freeze["code"]["source_hash"], "after": code_manifest()["source_hash"], "unchanged": freeze["code"]["source_hash"] == code_manifest()["source_hash"]})
    finally:
        await session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--policies", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-source", type=Path)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--arms", nargs="+", choices=("A", "B", "C"), default=["A", "B", "C"])
    args = parser.parse_args()
    if args.receiver:
        asyncio.run(receiver_main(json.loads(sys.stdin.readline())))
    else:
        if any(getattr(args, name) is None for name in ("dataset", "fixtures", "policies", "output", "runtime_source")):
            parser.error("Dataset, fixtures, policies, new output folder and runtime source are required.")
        asyncio.run(run_main(args))


if __name__ == "__main__":
    main()
