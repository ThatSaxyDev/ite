import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch
import httpx

from ite.client.response import StreamEvent
from ite.client.response import StreamEventType
from ite.client.response import TextDelta
from ite.client.llm_client import LLMClient
from ite.config.config import Config


class _FakeResponse:
    status_code = 200

    def __init__(self, *, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True, "output": "hi", "usage": {}}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, capture: list[dict], responses: list[object] | None = None) -> None:
        self._capture = capture
        self._responses = responses or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self._capture.append({"url": url, "headers": headers or {}, "json": json or {}})
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return _FakeResponse()


class LLMClientTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _config() -> Config:
        return Config(model={"name": "local-test"})

    async def test_complete_text_returns_final_text(self) -> None:
        client = LLMClient(self._config())
        client._non_stream_response = AsyncMock(
            return_value=StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=TextDelta(content="feat: simplify commits"),
            )
        )
        client.get_client = lambda: object()

        text = await client.complete_text([{"role": "user", "content": "hello"}])

        self.assertEqual(text, "feat: simplify commits")

    async def test_complete_text_raises_on_empty_output(self) -> None:
        client = LLMClient(self._config())
        client._non_stream_response = AsyncMock(
            return_value=StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)
        )
        client.get_client = lambda: object()

        with self.assertRaisesRegex(
            ValueError, "Commit subject generation returned an empty response."
        ):
            await client.complete_text([{"role": "user", "content": "hello"}])

    async def test_cloud_requests_omit_optional_tool_fields_when_unused(self) -> None:
        captured: list[dict] = []
        config = Config()
        client = LLMClient(config)

        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(capture=captured)

        with (
            patch("ite.client.llm_client.get_cloud_session", return_value=session),
            patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client),
        ):
            events = []
            async for event in client._cloud_chat_completion(
                [{"role": "user", "content": "hello"}],
                tools=None,
            ):
                events.append(event)

        self.assertTrue(events)
        payload = captured[0]["json"]
        self.assertEqual(payload["model"], "kimi-k2.5")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("tools", payload)
        self.assertNotIn("toolChoice", payload)

    def test_format_cloud_error_surfaces_provider_failure_details(self) -> None:
        client = LLMClient(self._config())

        message = client._format_cloud_error(
            {
                "error": {
                    "code": "provider_request_failed",
                    "message": "Bundled inference provider request failed.",
                    "details": {
                        "provider": "minimax",
                        "providerStatus": 500,
                        "providerRef": "abc-123",
                        "providerMessage": "Provider request failed (500): Internal Server Error",
                    },
                }
            }
        )

        self.assertIn("provider failed", message.lower())
        self.assertIn("minimax", message.lower())
        self.assertIn("500", message)
        self.assertIn("abc-123", message)

    def test_cloud_suffix_uses_local_provider_when_user_base_url_is_configured(self) -> None:
        config = Config(
            model={"name": "kimi-k2.5:cloud"},
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        client = LLMClient(config)

        self.assertFalse(client._is_cloud_model())

    async def test_cloud_chat_completion_retries_transient_provider_failure(self) -> None:
        captured: list[dict] = []
        config = Config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        responses: list[object] = [
            _FakeResponse(
                status_code=502,
                payload={
                    "ok": False,
                    "error": {
                        "code": "provider_request_failed",
                        "details": {
                            "provider": "ollama-dev",
                            "providerStatus": 500,
                            "providerMessage": "Internal Server Error",
                        },
                    },
                },
            ),
            _FakeResponse(),
        ]

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(capture=captured, responses=responses)

        with (
            patch("ite.client.llm_client.get_cloud_session", return_value=session),
            patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client),
            patch("ite.client.llm_client.asyncio.sleep", new=AsyncMock()),
        ):
            events = []
            async for event in client._cloud_chat_completion(
                [{"role": "user", "content": "hello"}],
                tools=None,
            ):
                events.append(event)

        self.assertEqual(len(captured), 2)
        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)

    async def test_cloud_complete_text_retries_transient_connection_error(self) -> None:
        captured: list[dict] = []
        config = Config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        responses: list[object] = [
            httpx.ConnectError("connection reset"),
            _FakeResponse(payload={"ok": True, "output": "continued", "usage": {}}),
        ]

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(capture=captured, responses=responses)

        with (
            patch("ite.client.llm_client.get_cloud_session", return_value=session),
            patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client),
            patch("ite.client.llm_client.asyncio.sleep", new=AsyncMock()),
        ):
            text = await client._cloud_complete_text([{"role": "user", "content": "hello"}])

        self.assertEqual(text, "continued")
        self.assertEqual(len(captured), 2)

    async def test_cloud_chat_completion_falls_back_to_saved_provider_on_entitlement_denied(self) -> None:
        captured: list[dict] = []
        config = Config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(
                capture=captured,
                responses=[
                    _FakeResponse(
                        status_code=403,
                        payload={
                            "ok": False,
                            "error": {
                                "code": "entitlement_denied",
                                "message": "Bundled access is not enabled for this account.",
                            },
                        },
                    )
                ],
            )

        async def _fake_stream_response(_client, kwargs):
            self.assertEqual(kwargs["model"], "ollama/deepseek-r1")
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content="Recovered locally."),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)

        client.get_client = lambda: object()
        client._stream_response = _fake_stream_response

        with (
            patch("ite.client.llm_client.get_cloud_session", return_value=session),
            patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client),
            patch(
                "ite.client.llm_client.load_saved_custom_provider",
                return_value={
                    "ollama/deepseek-r1": {
                        "model_name": "ollama/deepseek-r1",
                        "api_key": "ollama",
                        "base_url": "http://localhost:11434/v1",
                    }
                },
            ),
        ):
            events = []
            async for event in client.chat_completion(
                [{"role": "user", "content": "hello"}],
                tools=None,
            ):
                events.append(event)

        self.assertEqual(events[0].text_delta.content, "Recovered locally.")
        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)
        self.assertEqual(client.config.model_name, "ollama/deepseek-r1")
        self.assertEqual(client.config.base_url, "http://localhost:11434/v1")

    async def test_cloud_complete_text_falls_back_to_saved_provider_on_entitlement_denied(self) -> None:
        captured: list[dict] = []
        config = Config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(
                capture=captured,
                responses=[
                    _FakeResponse(
                        status_code=403,
                        payload={
                            "ok": False,
                            "error": {
                                "code": "entitlement_denied",
                                "message": "Bundled access is not enabled for this account.",
                            },
                        },
                    )
                ],
            )

        client.get_client = lambda: object()
        client._non_stream_response = AsyncMock(
            return_value=StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=TextDelta(content="Recovered locally."),
            )
        )

        with (
            patch("ite.client.llm_client.get_cloud_session", return_value=session),
            patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client),
            patch(
                "ite.client.llm_client.load_saved_custom_provider",
                return_value={
                    "ollama/deepseek-r1": {
                        "model_name": "ollama/deepseek-r1",
                        "api_key": "ollama",
                        "base_url": "http://localhost:11434/v1",
                    }
                },
            ),
        ):
            text = await client.complete_text([{"role": "user", "content": "hello"}])

        self.assertEqual(text, "Recovered locally.")
        self.assertEqual(client.config.model_name, "ollama/deepseek-r1")
        self.assertEqual(client.config.base_url, "http://localhost:11434/v1")

    async def test_chat_completion_preserves_model_name_for_user_provider_requests(self) -> None:
        config = Config(
            model={"name": "kimi-k2.5:cloud"},
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        client = LLMClient(config)

        captured_kwargs: dict = {}

        async def _fake_stream_response(_client, kwargs):
            captured_kwargs.update(kwargs)
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)

        client.get_client = lambda: object()
        client._stream_response = _fake_stream_response

        events = []
        async for event in client.chat_completion(
            [{"role": "user", "content": "hello"}],
            tools=None,
        ):
            events.append(event)

        self.assertEqual(captured_kwargs["model"], "kimi-k2.5:cloud")
        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)


if __name__ == "__main__":
    unittest.main()
