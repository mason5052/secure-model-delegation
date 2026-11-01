"""Authenticated agent protocol adapter. Policy checks precede external dispatch."""

from __future__ import annotations

import copy
import asyncio
import hmac
import json
import time
import uuid
from collections import deque
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .engine import execute, _deterministic_findings
from .providers import ProviderError
from .store import digest


ALIASES = {"smd-local": "local", "smd-openai": "openai", "smd-anthropic": "anthropic", "smd-remote": "remote"}


def validate_envelope(body: dict) -> dict:
    if not isinstance(body, dict) or body.get("model") not in ALIASES:
        raise ValueError("Select an SMD model alias.")
    allowed = {"model", "messages", "tools", "tool_choice", "parallel_tool_calls", "max_tokens", "max_completion_tokens", "temperature", "top_p", "stream", "stream_options", "stop", "response_format", "frequency_penalty", "presence_penalty", "seed", "reasoning_effort"}
    if set(body) - allowed:
        raise ValueError("The agent request contains unsupported protocol fields.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 200:
        raise ValueError("Provide a bounded conversation including tool results.")
    calls, results = set(), set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError("Invalid agent message role.")
        content = message.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise ValueError("Invalid message content.")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or part.get("type") not in {"text", "image_url"}:
                    raise ValueError("Only text and inline image parts are supported.")
                if part["type"] == "image_url" and not str(part.get("image_url", {}).get("url", "")).startswith("data:image/"):
                    raise ValueError("Remote image URLs are not fetched by model adapters. Attach inline images.")
        for call in message.get("tool_calls", []):
            if call.get("type") != "function" or not isinstance(call.get("id"), str):
                raise ValueError("Invalid function call.")
            json.loads(call["function"]["arguments"])
            if call["id"] in calls:
                raise ValueError("Duplicate tool call ID.")
            calls.add(call["id"])
        if message["role"] == "tool":
            if message.get("tool_call_id") not in calls or message["tool_call_id"] in results:
                raise ValueError("A tool result must reference a preceding unique tool call.")
            results.add(message["tool_call_id"])
    if len(json.dumps(body).encode()) > 2 * 1024**2:
        raise ValueError("The complete request exceeds the agent context limit; history was not truncated.")
    return copy.deepcopy(body)


def protocol_signature(body: dict) -> list:
    return [(m["role"], m.get("tool_call_id"), [(c.get("id"), c.get("type"), c.get("function", {}).get("name")) for c in m.get("tool_calls", [])]) for m in body["messages"]]


def anthropic_body(body: dict, model: str) -> dict:
    messages, system = [], []
    for source in body["messages"]:
        role, content = source["role"], source.get("content") or ""
        if role in {"system", "developer"}:
            system.append(content if isinstance(content, str) else json.dumps(content))
            continue
        blocks = []
        if role == "tool":
            blocks.append({"type": "tool_result", "tool_use_id": source["tool_call_id"], "content": content})
            role = "user"
        elif isinstance(content, str):
            if content:
                blocks.append({"type": "text", "text": content})
        else:
            for part in content:
                if part["type"] == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                else:
                    prefix, encoded = part["image_url"]["url"].split(",", 1)
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": prefix[5:].split(";")[0], "data": encoded}})
        for call in source.get("tool_calls", []):
            blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(call["function"]["arguments"])})
        messages.append({"role": role, "content": blocks or [{"type": "text", "text": " "}]})
    result = {"model": model, "max_tokens": min(8192, body.get("max_tokens", body.get("max_completion_tokens", 2048))), "messages": messages}
    if system:
        result["system"] = "\n\n".join(system)
    if body.get("tools"):
        result["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"].get("parameters", {"type": "object"})} for t in body["tools"]]
    return result


async def provider_agent_complete(registry, destination: str, body: dict) -> tuple[dict, dict]:
    entry = registry._entries.get(destination)
    if entry is None:
        raise ProviderError("Configure this connection first.", code="not_configured")
    if destination == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": entry.key, "anthropic-version": "2026-10-21"}
        outgoing = anthropic_body(body, entry.model)
    else:
        base = entry.base_url if destination == "remote" else "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + entry.key}
        outgoing = {k: v for k, v in body.items() if k not in {"stream", "stream_options", "model"}}
        outgoing.update(model=entry.model, stream=False)
        if destination == "openai":
            outgoing["store"] = False
    try:
        async with httpx.AsyncClient(transport=registry._transport, trust_env=False, follow_redirects=False, timeout=registry._timeout) as client:
            response = await client.post(url, headers=headers, json=outgoing)
            if response.status_code >= 300:
                raise ProviderError(f"Provider returned HTTP {response.status_code}.", code="provider_rejected")
            if len(response.content) > 8 * 1024**2:
                raise ProviderError("Provider response exceeded the limit.", code="invalid_response")
            data = response.json()
    except httpx.RequestError:
        raise ProviderError("External delivery is uncertain; no retry was attempted.", code="delivery_unknown", delivery_unknown=True) from None
    if destination == "anthropic":
        message = {"role": "assistant", "content": "\n".join(c["text"] for c in data.get("content", []) if c.get("type") == "text")}
        calls = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["input"])}} for c in data.get("content", []) if c.get("type") == "tool_use"]
        if calls:
            message["tool_calls"] = calls
        data = {"id": data.get("id", "chatcmpl-" + uuid.uuid4().hex), "object": "chat.completion", "created": int(time.time()), "model": body["model"], "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}], "usage": data.get("usage", {})}
    return data, outgoing


class AgentGateway:
    def __init__(self, runtime, providers, store, token: str, operation_lock=None):
        self.runtime, self.providers, self.store, self.token = runtime, providers, store, token
        self.records = deque(maxlen=100)
        self.lock = operation_lock or asyncio.Lock()

    async def complete(self, raw: dict) -> dict:
        async with self.lock:
            return await self._complete(raw)

    async def _complete(self, raw: dict) -> dict:
        body = validate_envelope(raw)
        destination = ALIASES[body["model"]]
        state = await self.runtime.status()
        if not state.get("ready"):
            raise ValueError("Install and activate a local model first.")
        policy = self.store.policy()
        rules = {k: policy[k] for k in ("version", "title", "source_text", "rules", "issues")}
        audit = {"id": uuid.uuid4().hex, "created_at": time.time(), "destination": destination, "request_hash": digest(body), "external_attempted": False}
        captured = None

        async def inspect_chat(messages, **kwargs):
            if kwargs.get("schema") is not None:
                if destination == "local" and not any("local" in rule["targets"] and rule["action"] in {"deny", "clarify"} for rule in rules["rules"]):
                    return json.dumps({"uncertain": True, "reason": "The request stays local; pattern checks remain active.", "findings": [], "local_feasibility": "sufficient"})
                return await self.runtime.chat(messages, **kwargs)
            return "The protocol adapter will generate the actual answer on the selected route."

        async def capture(_, outgoing):
            nonlocal captured
            captured = json.loads(outgoing[-1]["content"])
            return "The checked agent request is ready."

        async def emit(event):
            pass

        # Serialize the entire model request, including tool definitions and earlier results.
        # Invalid JSON after redaction safely keeps the original request on the local model.
        try:
            result = await execute([{"role": "user", "content": json.dumps(body, ensure_ascii=False)}], rules, destination, inspect_chat, capture if destination != "local" else None, emit)
        except (ValueError, TypeError, json.JSONDecodeError):
            result = {"route": "ask_clarification", "answer": "The complete agent envelope could not be checked under the active policy. Shorten the session or review the policy before continuing.", "rule_ids": [], "reasons": ["The complete agent envelope could not be safely checked."], "inspection": {"reliable": False}}
        audit.update({k: result.get(k) for k in ("route", "rule_ids", "reasons", "inspection")})
        if destination == "local" and not any("local" in rule["targets"] and rule["action"] in {"deny", "clarify"} for rule in rules["rules"]):
            audit["inspection"] = {"reliable": False, "uncertain": True, "mode": "local_pattern_checks",
                                   "reason": "The local-only route used pattern checks. Semantic inspection was not performed."}
        try:
            if result["route"] in {"deny_request", "ask_clarification"}:
                reply = {"id": "chatcmpl-" + audit["id"], "object": "chat.completion", "created": int(time.time()), "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": result["answer"]}, "finish_reason": "stop"}]}
            elif captured is not None and protocol_signature(captured) == protocol_signature(body) and not _deterministic_findings([{"role": "user", "content": json.dumps(captured)}]):
                audit["external_attempted"] = True
                reply, actual_body = await provider_agent_complete(self.providers, destination, captured)
                audit["outbound_hash"] = digest(actual_body)
                audit["payload"] = actual_body
            else:
                audit["route"] = "local_process"
                reply = await self.runtime.agent_complete(body)
            audit["status"] = "completed"
            return reply
        except (RuntimeError, httpx.HTTPError) as exc:
            audit["error"] = str(exc)[:300]
            raise
        finally:
            audit.setdefault("status", "failed")
            self.records.append(audit)
            self.store.begin_run(audit["id"], "agent", destination, policy["id"], state, body["messages"])
            if audit["status"] == "completed":
                self.store.finish_run(audit["id"], {"route": audit["route"], "external_attempted": audit["external_attempted"], "payload": audit.get("payload")}, body["messages"], self.store.settings()["save_content"])
            else:
                self.store.fail_run(audit["id"], "agent_failed", audit["external_attempted"], delivery_unknown=audit["external_attempted"])


def create_gateway_router(gateway: AgentGateway) -> APIRouter:
    router = APIRouter(prefix="/api/v1/gateway/v1")

    @router.get("/models")
    async def models():
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "smd"} for m in ALIASES]}

    @router.post("/chat/completions")
    async def complete(request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + gateway.token):
            raise HTTPException(401, "An internal agent token is required.")
        try:
            body = await request.json()
            result = await gateway.complete(body)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "The request or selected model is unsupported; the complete history was preserved.") from None
        except (RuntimeError, httpx.HTTPError):
            # Return a non-retryable protocol error, including uncertain deliveries.
            # The agent must not turn a timeout into repeated external charges.
            raise HTTPException(422, "The selected model could not complete the full request. Check model capability, context and memory. No automatic retry or alternate external destination was attempted.") from None
        if not body.get("stream"):
            return JSONResponse(result)

        async def chunks():
            common = {"id": result["id"], "object": "chat.completion.chunk", "created": result.get("created", int(time.time())), "model": body["model"]}
            choice = result["choices"][0]
            delta = copy.deepcopy(choice["message"])
            for index, call in enumerate(delta.get("tool_calls", [])):
                call["index"] = index
            yield "data: " + json.dumps({**common, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({**common, "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}], "usage": result.get("usage", {})}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")

    return router
