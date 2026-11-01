import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from smd_app.mlx_runtime import ManagedMLX


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        for index in range(0, len(self.data), 65536):
            await asyncio.sleep(0)
            yield self.data[index:index + 65536]


class ModelDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_weight_file_resumes_with_range_and_matches_full_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ManagedMLX(Path(directory))
            data = bytes(range(256)) * 8192
            expected = hashlib.sha256(data).hexdigest()
            details = {"revision": "a" * 40, "variants": [{"installable": True, "size_bytes": len(data)}],
                       "files": [{"rfilename": "model.safetensors", "size": len(data), "lfs": {"sha256": expected}}]}
            ranges = []

            def receive(request):
                offset = int(request.headers.get("range", "bytes=0-").split("=")[1].split("-")[0])
                ranges.append(offset)
                return httpx.Response(206 if offset else 200, stream=Chunks(data[offset:]))

            client_type = httpx.AsyncClient

            def client(**kwargs):
                return client_type(**kwargs, transport=httpx.MockTransport(receive))

            async def stop_after_progress(event):
                if event.get("completed", 0) >= 65536:
                    raise asyncio.CancelledError()

            async def progress(event):
                pass

            with patch.object(runtime, "command", return_value=["test-engine"]), \
                 patch.object(runtime, "details", AsyncMock(return_value=details)), \
                 patch("smd_app.mlx_runtime.httpx.AsyncClient", client):
                with self.assertRaises(asyncio.CancelledError):
                    await runtime.install("mlx:synthetic/model", stop_after_progress)
                partial = runtime.model_path("mlx:synthetic/model") / "model.safetensors.partial"
                retained = partial.stat().st_size
                self.assertGreater(retained, 0)
                self.assertLess(retained, len(data))
                result = await runtime.install("mlx:synthetic/model", progress)
                self.assertTrue(result["installed"])
                self.assertFalse(result["selected"])
            self.assertEqual(ranges, [0, retained])
            final = runtime.model_path("mlx:synthetic/model") / "model.safetensors"
            self.assertEqual(hashlib.sha256(final.read_bytes()).hexdigest(), expected)
            self.assertFalse(partial.exists())

    async def test_insufficient_space_rejects_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ManagedMLX(Path(directory))
            details = {"variants": [{"installable": True, "size_bytes": 2**40}]}
            with patch.object(runtime, "command", return_value=["test-engine"]), \
                 patch.object(runtime, "details", AsyncMock(return_value=details)):
                with self.assertRaisesRegex(RuntimeError, "disk space"):
                    await runtime.install("mlx:synthetic/model", AsyncMock())
