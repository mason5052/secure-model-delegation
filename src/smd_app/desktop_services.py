"""Local voice and policy-mediated web/MCP adapters for the desktop application."""

from __future__ import annotations

import base64
import asyncio
import contextlib
import io
import ipaddress
import json
import socket
import wave
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException

from .engine import execute
from .hub import HubCatalog


class TextPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"p", "div", "h1", "h2", "li", "br"}:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


class DesktopServices:
    def __init__(self, runtime, store, operation_lock=None):
        self.runtime, self.store = runtime, store
        self.lock = operation_lock or asyncio.Lock()
        self.voice_model = None
        self.search_url = None
        if hasattr(runtime, "mlx"):
            with contextlib.suppress(OSError, ValueError):
                self.voice_model = json.loads((runtime.mlx.data_dir / "voice.json").read_text())["model"]

    async def authorize(self, value, purpose):
        policy = self.store.policy()
        policy = {k: policy[k] for k in ("version", "title", "source_text", "rules", "issues")}
        checked = None

        async def chat(messages, **kwargs):
            raw = await self.runtime.chat(messages, **kwargs)
            if kwargs.get("schema"):
                assessment = json.loads(raw)
                # The user explicitly requested a network operation. This does not
                # change sensitivity findings or authorization from the policy.
                assessment["local_feasibility"] = "insufficient"
                return json.dumps(assessment)
            return "This network operation remains blocked."

        async def capture(_, outgoing):
            nonlocal checked
            checked = json.loads(outgoing[-1]["content"])
            return "Checked."

        async def emit(event):
            pass

        try:
            result = await execute([{"role": "user", "content": json.dumps(value, ensure_ascii=False)}], policy, purpose, chat, capture, emit)
        except (ValueError, RuntimeError):
            raise HTTPException(403, "The complete network request could not be checked under the active policy.") from None
        if result["route"] != "delegate_sanitized_to_external_ai" or checked != value:
            raise HTTPException(403, "The active policy keeps this network request local or requires changes. No request was sent.")

    async def public_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise HTTPException(422, "Use a public HTTPS URL without embedded credentials.")
        try:
            addresses = await __import__("asyncio").get_running_loop().getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
                raise ValueError
        except (OSError, ValueError):
            raise HTTPException(422, "The URL must resolve to a public address.") from None

    async def read_web(self, url):
        await self.public_url(url)
        await self.authorize({"url": url, "method": "GET"}, "web")
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as client:
            async with client.stream("GET", url, headers={"User-Agent": "SMD-Desktop/0.3"}) as response:
                if response.status_code >= 300:
                    raise HTTPException(409, "The page redirected or could not be read. Enter its final public URL explicitly.")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 4 * 1024**2:
                        raise HTTPException(413, "This page exceeds the preview limit.")
                text = data.decode("utf-8", errors="replace")
        parser = TextPage()
        parser.feed(text)
        return {"url": url, "title": urlsplit(url).hostname, "text": "".join(parser.parts)[:200000], "scope": "Public page text; scripts and active content are not executed."}

    async def network_request(self, *, url, messages, purpose="mcp"):
        await self.public_url(url)
        await self.authorize({"url": url, "messages": messages}, purpose)
        headers = {"Accept": "application/json, text/event-stream"}
        reply = None
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
            for message in messages:
                async with client.stream("POST", url, headers=headers, json=message) as response:
                    if response.status_code >= 300:
                        raise HTTPException(409, "The remote MCP endpoint rejected the checked request.")
                    if response.headers.get("mcp-session-id"):
                        headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1024**2:
                            raise HTTPException(413, "The remote tool result exceeds the response limit.")
                        if "text/event-stream" in response.headers.get("content-type", "") and b"\n\n" in data:
                            break
                    if data:
                        text = data.decode()
                        reply = json.loads(next((line[6:] for line in text.splitlines() if line.startswith("data: ")), text))
        return reply


def create_desktop_services_router(service):
    router = APIRouter(prefix="/api/v1")

    @router.get("/voice/status")
    async def voice_status():
        mlx = getattr(service.runtime, "mlx", None)
        return {"available": bool(mlx), "selected_model": service.voice_model, "model": service.voice_model, "engine": "MLX-Audio", "download_required": not service.voice_model, "format": "WAV PCM", "speech_output": "Installed macOS voices"}

    @router.get("/voice/catalog")
    async def voice_catalog(query: str = ""):
        data = await HubCatalog()._get("/api/models", {"filter": "mlx", "pipeline_tag": "automatic-speech-recognition", "search": query[:120], "sort": "lastModified", "limit": 24})
        return {"models": [{"id": "mlx:" + item["id"], "name": item["id"]} for item in data]}

    @router.post("/voice/install")
    async def voice_install(body: dict):
        mlx = getattr(service.runtime, "mlx", None)
        if not mlx:
            raise HTTPException(409, "Use the complete desktop distribution for local speech recognition.")
        model = body.get("model", "")
        if not model.startswith("mlx:"):
            model = "mlx:" + model
        async def emit(event):
            pass
        try:
            async with service.lock:
                await mlx.install(model, emit)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)[:300]) from None
        service.voice_model = model
        (mlx.data_dir / "voice.json").write_text(json.dumps({"model": model}))
        return await voice_status()

    @router.post("/voice/transcribe")
    async def transcribe(body: dict):
        mlx = getattr(service.runtime, "mlx", None)
        if not mlx or not service.voice_model:
            raise HTTPException(409, "Select and install a local speech model first.")
        try:
            audio = base64.b64decode(body["audio_base64"], validate=True)
            if len(audio) > 16 * 1024**2:
                raise ValueError
            with wave.open(io.BytesIO(audio)) as recording:
                if recording.getnframes() / recording.getframerate() > 180:
                    raise ValueError
        except (ValueError, KeyError, wave.Error):
            raise HTTPException(422, "Record a PCM WAV clip shorter than three minutes and 16 MB.") from None
        try:
            async with service.lock:
                await mlx.start()
                data = await mlx.request("POST", "/v1/audio/transcriptions", data={"model": mlx.model_path(service.voice_model).name}, files={"file": ("recording.wav", audio, "audio/wav")})
        except (RuntimeError, httpx.HTTPError):
            raise HTTPException(409, "The local speech model could not transcribe this clip. Check speech-model compatibility and available memory.") from None
        return {"text": data.get("text", ""), "local": True, "saved": False}

    @router.post("/web/read")
    async def read(body: dict):
        try:
            return await service.read_web(body["url"])
        except (KeyError, ValueError, httpx.HTTPError):
            raise HTTPException(409, "The public page could not be read.") from None

    @router.put("/web/search-provider")
    async def configure_search(body: dict):
        await service.public_url(body.get("url", ""))
        service.search_url = body["url"]
        return {"configured": True, "type": "SearXNG JSON"}

    @router.post("/web/search")
    async def search(body: dict):
        if not service.search_url:
            raise HTTPException(409, "Configure a public SearXNG JSON search endpoint first.")
        query = body.get("query", "")
        if not isinstance(query, str) or not 1 <= len(query) <= 1000:
            raise HTTPException(422, "Enter a bounded search query.")
        await service.authorize({"url": service.search_url, "query": query}, "web")
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as client:
            response = await client.get(service.search_url, params={"q": query, "format": "json"})
            if response.status_code >= 300 or len(response.content) > 4 * 1024**2:
                raise HTTPException(409, "The configured search endpoint is unavailable.")
            return {"results": [{k: item.get(k) for k in ("title", "url", "content")} for item in response.json().get("results", [])[:20]]}

    return router
