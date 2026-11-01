"""Public Hugging Face GGUF catalog metadata; never runs remote inference."""

from __future__ import annotations

import copy
import json
import re
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


HUB_ORIGIN = "https://huggingface.co"
MAX_METADATA_BYTES = 8 * 1024**2
SUPPORTED_TASKS = {"text-generation", "text2text-generation", "conversational", "image-text-to-text"}


class HubCatalogError(RuntimeError):
    """A public-catalog error safe to display without exposing response bodies."""


def validate_repo_id(repo: str) -> str:
    pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}"
    if not isinstance(repo, str) or not re.fullmatch(pattern, repo) or ".." in repo or "--" in repo or any(part.endswith((".", "-")) for part in repo.split("/")):
        raise HubCatalogError("Use a Hugging Face repository ID in author/model format.")
    return repo


def _text(value: Any, limit: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    return "".join(character for character in value if ord(character) >= 32 or character in "\n\t").strip()[:limit] or None


def _gated(data: dict) -> bool | None:
    value = data.get("gated")
    if value is False:
        return False
    if value is True or value in ("auto", "manual"):
        return True
    return None


def _license(data: dict) -> str | None:
    card = data.get("cardData")
    value = card.get("license") if isinstance(card, dict) else None
    if isinstance(value, list):
        return ", ".join(filter(None, (_text(item, 80) for item in value[:8]))) or None
    if _text(value, 200):
        return _text(value, 200)
    tags = data.get("tags")
    return next((tag[8:208] for tag in tags if isinstance(tag, str) and tag.startswith("license:")), None) if isinstance(tags, list) else None


def _quantization(filename: str) -> str:
    match = re.search(r"(?:^|[._-])((?:I|T)?Q\d+(?:_[A-Z0-9]+)*|BF16|FP16|F16|F32)(?=[._-]|$)", filename, re.IGNORECASE)
    return match.group(1).upper() if match else "Unknown"


def _file_size(item: dict) -> int | None:
    value = item.get("size")
    if not isinstance(value, int) or isinstance(value, bool):
        lfs = item.get("lfs")
        value = lfs.get("size") if isinstance(lfs, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class HubCatalog:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._cache: dict[tuple, tuple[float, dict]] = {}

    async def _get(self, path: str, params: dict) -> Any:
        location = HUB_ORIGIN + path
        try:
            async with httpx.AsyncClient(transport=self._transport, trust_env=False, timeout=httpx.Timeout(20, connect=5), follow_redirects=False, headers={"Accept": "application/json", "User-Agent": "SecureModelDelegation-PublicCatalog/0.2"}) as client:
                for _ in range(4):
                    parsed = urlparse(location)
                    if parsed.scheme != "https" or parsed.hostname != "huggingface.co" or parsed.port not in {None, 443} or not parsed.path.startswith("/api/models") or parsed.username:
                        raise HubCatalogError("The catalog redirected outside its approved metadata service.")
                    async with client.stream("GET", location, params=params) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = urljoin(location, response.headers.get("location", ""))
                            params = {}
                            continue
                        if response.status_code in {401, 403, 404}:
                            raise HubCatalogError("This repository is unavailable through the public catalog. Private or gated model access is not configured.")
                        if response.status_code == 429:
                            raise HubCatalogError("The public catalog is rate limited. Wait a moment and search again.")
                        if response.status_code != 200:
                            raise HubCatalogError("Hugging Face metadata is unavailable. Check the connection and retry.")
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > MAX_METADATA_BYTES:
                                raise HubCatalogError("This repository's metadata exceeds the catalog size limit.")
                        return json.loads(chunks)
                raise HubCatalogError("The catalog redirected too many times.")
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            raise HubCatalogError("The public catalog could not be reached or returned invalid metadata. Check the connection and retry.") from exc

    def _cached(self, key: tuple, error: HubCatalogError, *, details: bool = False) -> dict:
        if key not in self._cache:
            raise error
        saved, data = self._cache[key]
        result = copy.deepcopy(data)
        result.update({"cached": True, "offline": True, "cache_age_seconds": max(0, round(time.time() - saved)), "error": str(error)})
        if details:
            for variant in result["variants"]:
                variant.update({"installable": False, "reason": "Reconnect and refresh the repository metadata before downloading."})
        return result

    def _remember(self, key: tuple, data: dict) -> dict:
        if len(self._cache) >= 32:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.time(), copy.deepcopy(data))
        return data

    async def search(self, query: str = "", sort: str = "lastModified", limit: int = 24) -> dict:
        if not isinstance(query, str) or len(query) > 160 or any(ord(character) < 32 for character in query):
            raise HubCatalogError("Keep a model search below 160 characters.")
        if sort not in {"lastModified", "downloads"}:
            raise HubCatalogError("Sort models by lastModified or downloads.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 48:
            raise HubCatalogError("Request between 1 and 48 catalog results.")
        query = query.strip()
        key = ("search", query, sort, limit)
        try:
            data = await self._get("/api/models", {"filter": "gguf", "pipeline_tag": "text-generation", "search": query, "sort": sort, "direction": -1, "limit": limit, "full": "true", "cardData": "true"})
            if not isinstance(data, list):
                raise HubCatalogError("The catalog returned an unsupported search result.")
            models = []
            for item in data[:limit]:
                if not isinstance(item, dict) or item.get("private") is True:
                    continue
                try:
                    repo = validate_repo_id(item.get("id") or item.get("modelId"))
                except HubCatalogError:
                    continue
                task = item.get("pipeline_tag")
                if task and task not in SUPPORTED_TASKS:
                    continue
                card = item.get("cardData")
                description = _text(card.get("description")) if isinstance(card, dict) else None
                models.append({"id": repo, "name": repo.split("/", 1)[1], "author": repo.split("/", 1)[0], "downloads": item.get("downloads") if isinstance(item.get("downloads"), int) and item["downloads"] >= 0 else None, "last_modified": _text(item.get("lastModified") or item.get("last_modified"), 80), "license": _license(item), "format": "GGUF", "gated": _gated(item), "compatibility": "not_checked", "description": description or "Public GGUF repository. Local runtime compatibility has not been checked.", "url": HUB_ORIGIN + "/" + repo})
            result = {"models": models, "source": "Hugging Face", "query": query, "sort": sort, "limit": limit, "cached": False, "offline": False, "cache_age_seconds": 0, "fetched_at": datetime.now(timezone.utc).isoformat(), "scope": "Public GGUF text-generation repositories; compatibility is checked after download."}
            return self._remember(key, result)
        except HubCatalogError as exc:
            return self._cached(key, exc)

    async def details(self, repo: str) -> dict:
        repo = validate_repo_id(repo)
        key = ("details", repo)
        try:
            data = await self._get("/api/models/" + repo, {"blobs": "true"})
            if not isinstance(data, dict):
                raise HubCatalogError("The repository returned unsupported metadata.")
            actual_repo = validate_repo_id(data.get("id") or repo)
            siblings = data.get("siblings")
            if not isinstance(siblings, list):
                raise HubCatalogError("The repository did not provide a file list.")
            gated = _gated(data)
            task = data.get("pipeline_tag")
            restriction = None
            if data.get("private") is True or gated is True:
                restriction = "This app supports public ungated models. Repository access approval or authentication is not configured."
            elif gated is None:
                restriction = "The repository access status is unknown. Refresh its metadata before downloading."
            elif task and task not in SUPPORTED_TASKS:
                restriction = "This repository is not marked as a supported text-generation model."
            variants = []
            shard_groups: dict[tuple[str, int], list[dict]] = {}
            for item in siblings:
                if not isinstance(item, dict):
                    continue
                filename = item.get("rfilename")
                if not isinstance(filename, str) or len(filename) > 512 or not filename.lower().endswith(".gguf"):
                    continue
                normalized = PurePosixPath(filename)
                if normalized.is_absolute() or ".." in normalized.parts or "\\" in filename or ":" in filename:
                    continue
                shard = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})\.gguf", filename, re.IGNORECASE)
                if shard:
                    stem, part, count = shard.group(1), int(shard.group(2)), int(shard.group(3))
                    shard_groups.setdefault((stem, count), []).append({"filename": filename, "part": part, "size": _file_size(item)})
                    continue
                reason = restriction
                if len(normalized.parts) != 1:
                    reason = reason or "GGUF files in subfolders are listed but not supported by this native filename installer."
                if any(word in normalized.name.lower() for word in ("mmproj", "projector")):
                    reason = reason or "This is a projector file, not a standalone text model."
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", normalized.name):
                    reason = reason or "This filename cannot be represented by a safe native Ollama model tag."
                size = _file_size(item)
                variant = {"id": filename, "filename": filename, "quantization": _quantization(filename), "size_bytes": size, "size_gb": round(size / 1_000_000_000, 3) if size is not None else None, "model_ref": f"hf.co/{actual_repo}:{filename}" if reason is None else None, "installable": reason is None, "reason": reason, "compatibility": "not_checked", "files": [filename]}
                variants.append(variant)
            for (stem, count), files in shard_groups.items():
                complete = count > 1 and len(files) == count and {item["part"] for item in files} == set(range(1, count + 1))
                size = sum(item["size"] for item in files) if all(item["size"] is not None for item in files) else None
                reason = restriction or ("Split GGUF groups are not yet supported by this managed installer." if complete else "This split GGUF group is incomplete or inconsistent.")
                variants.append({"id": stem + ":split", "filename": stem + f"-00001-of-{count:05d}.gguf", "quantization": _quantization(stem), "size_bytes": size, "size_gb": round(size / 1_000_000_000, 3) if size is not None else None, "model_ref": None, "installable": False, "reason": reason, "compatibility": "not_checked", "files": [item["filename"] for item in sorted(files, key=lambda item: item["part"])], "shard_count": count, "shards_complete": complete})
            variants.sort(key=lambda item: (not item["installable"], item["quantization"] != "Q4_K_M", item["size_bytes"] is None, item["size_bytes"] or 0, item["filename"]))
            revision = data.get("sha")
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
                revision = None
            result = {"id": actual_repo, "name": actual_repo.split("/", 1)[1], "author": actual_repo.split("/", 1)[0], "revision": revision, "license": _license(data), "gated": gated, "private": data.get("private") is True, "pipeline_tag": _text(task, 80), "format": "GGUF" if variants else "unsupported", "variants": variants, "compatibility": "not_checked" if any(item["installable"] for item in variants) else "not_compatible", "reason": restriction or (None if variants else "No GGUF weights were found. Safetensors, PyTorch and MLX files are not supported by this local engine."), "source": "Hugging Face", "url": HUB_ORIGIN + "/" + actual_repo, "cached": False, "offline": False, "cache_age_seconds": 0, "fetched_at": datetime.now(timezone.utc).isoformat(), "note": "File format and downloadability do not establish architecture, chat template, structured-response or memory compatibility. The app checks execution after download."}
            return self._remember(key, result)
        except HubCatalogError as exc:
            return self._cached(key, exc, details=True)
