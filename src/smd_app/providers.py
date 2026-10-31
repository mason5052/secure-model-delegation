"""Text-only provider clients. Credentials stay in this process's memory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, delivery_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.delivery_unknown = delivery_unknown


@dataclass(frozen=True)
class _Configuration:
    key: str
    model: str


class ProviderRegistry:
    """Only the two official HTTPS destinations are supported; no automatic retry."""

    def __init__(self, *, transport: Any = None, timeout: float = 45.0):
        self._entries: dict[str, _Configuration] = {}
        self._transport = transport
        self._timeout = httpx.Timeout(timeout, connect=min(10.0, timeout))

    def configure(self, name: str, api_key: str, model: str) -> None:
        self._check_name(name)
        if not isinstance(api_key, str) or not 8 <= len(api_key) <= 512 or re.search(r"\s", api_key):
            raise ValueError("Enter a valid provider API key without whitespace.")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", model):
            raise ValueError("Enter a provider model identifier, not an endpoint URL.")
        if "://" in model:
            raise ValueError("Custom provider endpoints are not supported.")
        self._entries[name] = _Configuration(api_key, model)

    def remove(self, name: str) -> None:
        self._check_name(name)
        self._entries.pop(name, None)

    def configured(self, name: str) -> bool:
        return name in self._entries

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": name,
                "configured": name in self._entries,
                "model": self._entries[name].model if name in self._entries else "",
                "masked_key": "********" + self._entries[name].key[-4:] if name in self._entries else "",
            }
            for name in ("openai", "anthropic")
        ]

    @staticmethod
    def _check_name(name: str) -> None:
        if name not in {"openai", "anthropic"}:
            raise ValueError("Choose OpenAI or Anthropic.")

    async def complete(self, name: str, messages: list[dict[str, str]]) -> str:
        self._check_name(name)
        entry = self._entries.get(name)
        if entry is None:
            raise ProviderError("This provider is not configured.", code="not_configured")
        self._validate_messages(messages)
        if name == "openai":
            url = "https://api.openai.com/v1/responses"
            headers = {"Authorization": "Bearer " + entry.key}
            body = {"model": entry.model, "input": messages, "max_output_tokens": 1024, "store": False}
        else:
            url = "https://api.anthropic.com/v1/messages"
            # https://platform.claude.com/docs/en/api/migration-2026-10-21
            # Text-only requests omit the sampling parameters removed in this version.
            headers = {"x-api-key": entry.key, "anthropic-version": "2026-10-21"}
            body = {
                "model": entry.model,
                "max_tokens": 1024,
                "messages": [message for message in messages if message["role"] != "system"],
            }
            system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
            if system:
                body["system"] = system
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ProviderError("The provider could not be reached. No retry was attempted.", code="connection_failed") from None
        except httpx.TimeoutException:
            raise ProviderError(
                "The provider timed out after dispatch. Delivery is unknown; no retry was attempted.",
                code="delivery_unknown", delivery_unknown=True,
            ) from None
        except httpx.RequestError:
            raise ProviderError(
                "The connection ended after dispatch. Delivery is unknown; no retry was attempted.",
                code="delivery_unknown", delivery_unknown=True,
            ) from None
        if response.status_code >= 300:
            code = "authentication_failed" if response.status_code in {401, 403} else "provider_rejected"
            raise ProviderError(f"The provider returned HTTP {response.status_code}. No retry was attempted.", code=code)
        try:
            data = response.json()
            if name == "openai":
                if data.get("status") != "completed":
                    raise ValueError("incomplete response")
                texts = [
                    block["text"]
                    for item in data.get("output", []) if item.get("type") == "message"
                    for block in item.get("content", []) if block.get("type") == "output_text"
                ]
            else:
                if data.get("stop_reason") not in {"end_turn", "stop_sequence", "refusal"}:
                    raise ValueError("incomplete response")
                texts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
            answer = "\n".join(texts).strip()
            if not answer:
                raise ValueError("empty")
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError("The provider returned no complete usable text answer. No retry was attempted.", code="invalid_response") from None
        return answer

    @staticmethod
    def _validate_messages(messages: list[dict[str, str]]) -> None:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 65:
            raise ValueError("A bounded text conversation is required.")
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError("Only text messages are supported.")
            if message["role"] not in {"user", "assistant", "system"} or (message["role"] == "system" and index != 0):
                raise ValueError("Invalid message role.")
            if not isinstance(message["content"], str):
                raise ValueError("Only text messages are supported.")
