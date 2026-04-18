import unittest
from unittest.mock import patch

import httpx

from ite.config.config import Config
from ite.ui.reup.modals import SetupModal


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url, headers=None):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SetupModalTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_ollama_requires_running_service(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([httpx.ConnectError("connection refused")]),
        ):
            message = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="qwen2.5-coder:7b",
            )

        self.assertIn("Start Ollama first", message or "")

    async def test_probe_ollama_requires_selected_model(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"models": [{"name": "llama3.2:3b"}]})]
            ),
        ):
            message = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="qwen2.5-coder:7b",
            )

        self.assertIn("ollama pull qwen2.5-coder:7b", message or "")

    async def test_probe_openai_compatible_rejects_invalid_key(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([_FakeResponse(401)]),
        ):
            message = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="bad-key",
                model_name="openai/gpt-4.1-mini",
            )

        self.assertIn("rejected this API key", message or "")

    async def test_probe_openai_compatible_requires_model_in_provider_list(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"data": [{"id": "openai/gpt-4.1-mini"}]})]
            ),
        ):
            message = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="key",
                model_name="anthropic/claude-sonnet-4",
            )

        self.assertIn("not available on this provider", message or "")


if __name__ == "__main__":
    unittest.main()
