from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from smd_app.hub import HubCatalog, HubCatalogError, validate_repo_id


REPOSITORY = {
    "id": "example/Small-Instruct-GGUF", "sha": "b" * 40,
    "private": False, "gated": False, "pipeline_tag": "text-generation",
    "cardData": {"license": "apache-2.0"},
    "siblings": [
        {"rfilename": "Small-Instruct-Q4_K_M.gguf", "size": 270000000},
        {"rfilename": "Small-Instruct-Q8_0.gguf", "lfs": {"size": 480000000}},
        {"rfilename": "README.md", "size": 100},
    ],
}


class HubCatalogTests(unittest.IsolatedAsyncioTestCase):
    def catalog(self, metadata):
        return HubCatalog(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=metadata)))

    def test_repository_ids_reject_urls_and_path_traversal(self):
        for repo in ["https://huggingface.co/example/model", "../model", "example/../model", "example/model/extra", "example/model?token=x", "example/model%2fextra", "example/-model", "example/model..bad", "example/model--bad"]:
            with self.subTest(repo=repo), self.assertRaises(HubCatalogError):
                validate_repo_id(repo)
        self.assertEqual(validate_repo_id("Example-Org/Model_1.5-GGUF"), "Example-Org/Model_1.5-GGUF")

    async def test_search_uses_live_public_text_gguf_metadata_without_auth(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=[{
                "id": "example/Small-Instruct-GGUF", "downloads": 123,
                "lastModified": "2026-10-31T00:00:00.000Z", "gated": False,
                "pipeline_tag": "text-generation", "tags": ["gguf", "license:apache-2.0"],
            }])
        catalog = HubCatalog(transport=httpx.MockTransport(handler))
        result = await catalog.search("Small", "downloads", 12)
        request = requests[0]
        self.assertEqual(request.url.host, "huggingface.co")
        self.assertEqual(request.url.params["filter"], "gguf")
        self.assertEqual(request.url.params["pipeline_tag"], "text-generation")
        self.assertEqual(request.url.params["sort"], "downloads")
        self.assertEqual(request.url.params["search"], "Small")
        self.assertNotIn("authorization", request.headers)
        self.assertEqual(result["models"][0]["license"], "apache-2.0")
        self.assertEqual(result["models"][0]["compatibility"], "not_checked")
        self.assertFalse(result["cached"])

    async def test_search_discards_private_nontext_and_invalid_repositories(self):
        data = [
            {"id": "example/Text-GGUF", "pipeline_tag": "text-generation"},
            {"id": "example/Image-GGUF", "pipeline_tag": "text-to-image"},
            {"id": "example/Private-GGUF", "private": True},
            {"id": "example/model/path"},
        ]
        result = await self.catalog(data).search()
        self.assertEqual([item["id"] for item in result["models"]], ["example/Text-GGUF"])
        self.assertIsNone(result["models"][0]["gated"])

    async def test_search_validates_sort_and_bounds(self):
        catalog = self.catalog([])
        for arguments in [dict(sort="arbitrary"), dict(limit=1000), dict(limit=True), dict(query="x" * 161)]:
            with self.subTest(arguments=arguments), self.assertRaises(HubCatalogError):
                await catalog.search(**arguments)

    async def test_details_returns_exact_native_filename_reference(self):
        result = await self.catalog(REPOSITORY).details(REPOSITORY["id"])
        selected = result["variants"][0]
        self.assertEqual(selected["quantization"], "Q4_K_M")
        self.assertEqual(selected["size_bytes"], 270000000)
        self.assertEqual(selected["model_ref"], "hf.co/example/Small-Instruct-GGUF:Small-Instruct-Q4_K_M.gguf")
        self.assertTrue(selected["installable"])
        self.assertEqual(result["revision"], "b" * 40)
        self.assertEqual(result["compatibility"], "not_checked")
        self.assertEqual(result["variants"][1]["size_bytes"], 480000000)

    async def test_gated_or_unknown_access_is_not_installable(self):
        for gated in ["auto", "manual", True, None]:
            data = {**REPOSITORY, "gated": gated}
            result = await self.catalog(data).details(REPOSITORY["id"])
            self.assertTrue(all(not item["installable"] for item in result["variants"]))
            self.assertTrue(all(item["reason"] for item in result["variants"]))
            self.assertTrue(all(item["model_ref"] is None for item in result["variants"]))

    async def test_non_gguf_format_is_reported_as_unsupported(self):
        data = {**REPOSITORY, "siblings": [{"rfilename": "model.safetensors", "size": 1000}]}
        result = await self.catalog(data).details(REPOSITORY["id"])
        self.assertEqual(result["format"], "unsupported")
        self.assertEqual(result["compatibility"], "not_compatible")
        self.assertIn("Safetensors", result["reason"])

    async def test_subfolders_projectors_and_unsafe_filenames_are_not_installable(self):
        data = {**REPOSITORY, "siblings": [
            {"rfilename": "sub/Model-Q4_K_M.gguf", "size": 100},
            {"rfilename": "mmproj-model-f16.gguf", "size": 100},
            {"rfilename": "Model with spaces.gguf", "size": 100},
            {"rfilename": "../escaped.gguf", "size": 100},
            {"rfilename": "C:\\escaped.gguf", "size": 100},
        ]}
        result = await self.catalog(data).details(REPOSITORY["id"])
        self.assertEqual(len(result["variants"]), 3)
        self.assertTrue(all(not item["installable"] and item["reason"] for item in result["variants"]))

    async def test_shards_are_grouped_and_never_offer_first_shard_as_whole_model(self):
        data = {**REPOSITORY, "siblings": [
            {"rfilename": "Small-Q4_K_M-00001-of-00002.gguf", "size": 200},
            {"rfilename": "Small-Q4_K_M-00002-of-00002.gguf", "size": 300},
            {"rfilename": "Small-Q8_0-00001-of-00003.gguf", "size": 100},
        ]}
        result = await self.catalog(data).details(REPOSITORY["id"])
        self.assertEqual(len(result["variants"]), 2)
        complete = next(item for item in result["variants"] if item["shards_complete"])
        self.assertEqual(complete["size_bytes"], 500)
        self.assertEqual(complete["shard_count"], 2)
        self.assertFalse(complete["installable"])
        self.assertIsNone(complete["model_ref"])
        incomplete = next(item for item in result["variants"] if not item["shards_complete"])
        self.assertIn("incomplete", incomplete["reason"])

    async def test_search_cache_is_marked_offline_without_fake_freshness(self):
        healthy = True
        def handler(request):
            if healthy:
                return httpx.Response(200, json=[{"id": REPOSITORY["id"]}])
            return httpx.Response(503)
        catalog = HubCatalog(transport=httpx.MockTransport(handler))
        first = await catalog.search("small")
        healthy = False
        cached = await catalog.search("small")
        self.assertTrue(cached["cached"])
        self.assertTrue(cached["offline"])
        self.assertEqual(cached["fetched_at"], first["fetched_at"])
        with self.assertRaises(HubCatalogError):
            await catalog.search("uncached")

    async def test_offline_details_cache_disables_downloads(self):
        healthy = True
        def handler(request):
            return httpx.Response(200, json=REPOSITORY) if healthy else httpx.Response(503)
        catalog = HubCatalog(transport=httpx.MockTransport(handler))
        self.assertTrue((await catalog.details(REPOSITORY["id"]))["variants"][0]["installable"])
        healthy = False
        cached = await catalog.details(REPOSITORY["id"])
        self.assertTrue(cached["offline"])
        self.assertFalse(cached["variants"][0]["installable"])

    async def test_metadata_size_limit_is_enforced(self):
        with patch("smd_app.hub.MAX_METADATA_BYTES", 10):
            with self.assertRaisesRegex(HubCatalogError, "size limit"):
                await self.catalog(REPOSITORY).details(REPOSITORY["id"])

    async def test_metadata_redirect_cannot_reach_another_service(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://unapproved.example/model"})
        with self.assertRaisesRegex(HubCatalogError, "approved metadata"):
            await HubCatalog(transport=httpx.MockTransport(handler)).search()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
