from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from ite.client.ollama_metadata import discover_context_window


class OllamaMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, model: str, responses: dict) -> tuple[int | None, list]:
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            status, data = responses.get(str(request.url), (404, {}))
            return httpx.Response(status, json=data)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("ite.client.ollama_metadata.httpx.AsyncClient", return_value=client):
            limit = await discover_context_window("http://localhost:11434/v1", model)
        return limit, requests

    async def test_cloud_falls_back_to_public_exact_metadata_without_inference(self) -> None:
        limit, requests = await self.discover("kimi-k2.6:cloud", {
            "https://ollama.com/api/show": (200, {
                "model_info": {"general.architecture": "kimi-k2", "kimi-k2.context_length": 262144},
            }),
        })
        self.assertEqual(limit, 262144)
        self.assertEqual([r.url.path for r in requests], ["/api/show", "/api/show"])
        self.assertEqual(requests[-1].content, b'{"model":"kimi-k2.6"}')

    async def test_local_uses_running_allocation_instead_of_model_maximum(self) -> None:
        limit, requests = await self.discover("qwen3.5:9b", {
            "http://localhost:11434/api/ps": (200, {
                "models": [{"name": "qwen3.5:9b", "context_length": 4096}],
            }),
        })
        self.assertEqual(limit, 4096)
        self.assertEqual(len(requests), 1)

    async def test_local_uses_configured_parameter_capped_by_maximum(self) -> None:
        limit, _ = await self.discover("custom", {
            "http://localhost:11434/api/show": (200, {
                "parameters": "temperature 0.7\nnum_ctx 1000000",
                "model_info": {"general.architecture": "qwen", "qwen.context_length": 262144},
            }),
        })
        self.assertEqual(limit, 262144)

    async def test_local_maximum_alone_does_not_establish_effective_limit(self) -> None:
        limit, _ = await self.discover("custom", {
            "http://localhost:11434/api/show": (200, {
                "model_info": {"qwen.context_length": 262144},
            }),
        })
        self.assertIsNone(limit)

    async def test_unavailable_or_malformed_metadata_returns_unknown(self) -> None:
        for responses in ({}, {"http://localhost:11434/api/ps": (200, {"models": None})}):
            with self.subTest(responses=responses):
                limit, _ = await self.discover("custom", responses)
                self.assertIsNone(limit)
