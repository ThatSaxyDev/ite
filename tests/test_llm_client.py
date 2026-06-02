import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch
import httpx
import base64
import json

from ite.client.response import StreamEvent
from ite.client.response import StreamEventType
from ite.client.response import TextDelta
from ite.client.llm_client import LLMClient
from ite.config.config import Config


class _FakeResponse:
    status_code = 200

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict | None = None,
        stream_events: list[dict] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True, "output": "hi", "usage": {}}
        self._stream_events = stream_events

    def json(self):
        return self._payload

    async def aread(self):
        return json.dumps(self._payload).encode("utf-8")

    async def aiter_lines(self):
        if self.status_code != 200:
            yield json.dumps(self._payload)
            return
        if self._stream_events is not None:
            for event in self._stream_events:
                yield json.dumps(event)
            return
        yield json.dumps(
            {
                "type": "message_complete",
                "finishReason": "stop",
                "usage": {},
            }
        )


class _FakeStreamContext:
    def __init__(self, response: object) -> None:
        self._response = response

    async def __aenter__(self):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


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

    def stream(self, _method, url, headers=None, json=None):
        self._capture.append({"url": url, "headers": headers or {}, "json": json or {}})
        if self._responses:
            return _FakeStreamContext(self._responses.pop(0))
        return _FakeStreamContext(_FakeResponse())


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeChatCompletions:
    def __init__(self, response):
        self._response = response

    async def create(self, **_kwargs):
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response):
        self.chat = _Obj(completions=_FakeChatCompletions(response))


class _AsyncChunks:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _decode_cloud_envelope(payload: dict) -> dict:
    assert payload["payloadEncoding"] == "base64json"
    return json.loads(base64.urlsafe_b64decode(payload["payload"]).decode("utf-8"))


class LLMClientTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _config() -> Config:
        return Config(model={"name": "local-test"})

    @staticmethod
    def _bundled_config(model_name: str = "moonshotai/kimi-k2.5") -> Config:
        return Config(model={"name": model_name, "source_kind": "bundled"})

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
        config = self._bundled_config()
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
        envelope = captured[0]["json"]
        payload = _decode_cloud_envelope(envelope)
        self.assertEqual(payload["model"], "moonshotai/kimi-k2.5")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("tools", payload)
        self.assertNotIn("toolChoice", payload)
        self.assertNotIn("hello", json.dumps(envelope))

    async def test_cloud_stream_falls_back_to_plain_payload_for_old_api(self) -> None:
        captured: list[dict] = []
        config = self._bundled_config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        responses: list[object] = [
            _FakeResponse(
                status_code=400,
                payload={
                    "ok": False,
                    "error": {
                        "code": "invalid_request",
                        "details": {
                            "issues": {
                                "fieldErrors": {
                                    "model": ["Required"],
                                    "messages": ["Required"],
                                }
                            }
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
        ):
            events = []
            async for event in client._cloud_chat_completion(
                [{"role": "user", "content": "hello"}],
                tools=None,
            ):
                events.append(event)

        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["json"]["payloadEncoding"], "base64json")
        self.assertEqual(captured[1]["json"]["model"], "moonshotai/kimi-k2.5")
        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)

    async def test_cloud_stream_http_error_includes_endpoint_and_status(self) -> None:
        config = self._bundled_config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        original_async_client = httpx.AsyncClient

        def _handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                str(request.url),
                "http://127.0.0.1:4000/inference/chat",
            )
            return httpx.Response(502, content=b"")

        def _fake_async_client(*args, **kwargs):
            return original_async_client(
                transport=httpx.MockTransport(_handler),
                timeout=kwargs.get("timeout"),
            )

        with patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client):
            events = []
            async for event in client._stream_cloud_inference_events(
                session, {"model": "moonshotai/kimi-k2.5"}
            ):
                events.append(event)

        self.assertEqual(events[0].type, StreamEventType.ERROR)
        self.assertIn("HTTP 502", events[0].error)
        self.assertIn("http://127.0.0.1:4000/inference/chat", events[0].error)

    async def test_cloud_stream_html_403_reports_edge_block_without_raw_html(self) -> None:
        config = self._bundled_config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        original_async_client = httpx.AsyncClient

        def _handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["user-agent"], "ite-agent/0.0.84")
            self.assertEqual(request.headers["x-ite-client"], "terminal-runtime")
            return httpx.Response(
                403,
                content=b"<!DOCTYPE html><html><head><title>Blocked</title></head></html>",
                headers={"content-type": "text/html"},
            )

        def _fake_async_client(*args, **kwargs):
            return original_async_client(
                transport=httpx.MockTransport(_handler),
                timeout=kwargs.get("timeout"),
            )

        with patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client):
            events = []
            async for event in client._stream_cloud_inference_events(
                session, {"model": "moonshotai/kimi-k2.5"}
            ):
                events.append(event)

        self.assertEqual(events[0].type, StreamEventType.ERROR)
        self.assertIn("blocked before it reached the API app", events[0].error)
        self.assertIn("HTTP 403", events[0].error)
        self.assertNotIn("<!DOCTYPE html>", events[0].error)

    async def test_cloud_stream_generic_error_mentions_it_reached_endpoint(self) -> None:
        config = self._bundled_config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        original_async_client = httpx.AsyncClient

        def _handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=(
                    b'{"type":"error","error":'
                    b'{"message":"Bundled inference request failed."}}\n'
                ),
            )

        def _fake_async_client(*args, **kwargs):
            return original_async_client(
                transport=httpx.MockTransport(_handler),
                timeout=kwargs.get("timeout"),
            )

        with patch("ite.client.llm_client.httpx.AsyncClient", side_effect=_fake_async_client):
            events = []
            async for event in client._stream_cloud_inference_events(
                session, {"model": "moonshotai/kimi-k2.5"}
            ):
                events.append(event)

        self.assertEqual(events[0].type, StreamEventType.ERROR)
        self.assertIn("after reaching", events[0].error)
        self.assertIn("http://127.0.0.1:4000/inference/chat", events[0].error)

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

    def test_format_cloud_error_points_entitlement_denied_to_pricing(self) -> None:
        client = LLMClient(self._config())

        message = client._format_cloud_error(
            {
                "error": {
                    "code": "entitlement_denied",
                    "message": "Bundled access is not enabled for this account.",
                }
            }
        )

        self.assertIn("/pricing", message)
        self.assertIn("iTE Pro", message)
        self.assertIn("own model provider", message)

    def test_format_cloud_error_points_quota_exhausted_to_billing_usage(self) -> None:
        client = LLMClient(self._config())

        message = client._format_cloud_error(
            {
                "error": {
                    "code": "quota_exhausted",
                    "message": "Bundled usage limit reached.",
                    "details": {"window": "seven_day"},
                }
            }
        )

        self.assertIn("account billing", message)
        self.assertIn("own key", message)
        self.assertIn("local model", message)

    def test_format_cloud_error_labels_monthly_quota_window(self) -> None:
        client = LLMClient(self._config())

        message = client._format_cloud_error(
            {
                "error": {
                    "code": "quota_exhausted",
                    "message": "Bundled usage limit reached.",
                    "details": {"window": "thirty_day"},
                }
            }
        )

        self.assertIn("30-day window", message)

    def test_cloud_suffix_uses_local_provider_when_user_base_url_is_configured(self) -> None:
        config = Config(
            model={"name": "kimi-k2.5:cloud"},
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        client = LLMClient(config)

        self.assertFalse(client._is_cloud_model())

    def test_model_without_user_credentials_routes_through_cloud(self) -> None:
        config = Config(
            model={"name": "moonshotai/kimi-k2.5", "source_kind": "bundled"},
            api_key="",
            base_url="",
        )
        client = LLMClient(config)

        self.assertTrue(client._is_cloud_model())

    def test_saved_profile_for_current_model_prevents_cloud_routing(self) -> None:
        config = Config(
            model={"name": "moonshotai/kimi-k2.5"},
            api_key="",
            base_url="",
        )
        client = LLMClient(config)

        with patch(
            "ite.client.llm_client.load_saved_custom_provider",
            return_value={
                "moonshotai/kimi-k2.5": {
                    "model_name": "moonshotai/kimi-k2.5",
                    "api_key": "sk-local",
                    "base_url": "https://openrouter.ai/api/v1",
                }
            },
        ):
            self.assertFalse(client._is_cloud_model())

    def test_cloud_model_name_resolution_preserves_canonical_bundled_ids(self) -> None:
        self.assertEqual(
            LLMClient(
                Config(model={"name": "minimax/minimax-m2.5", "source_kind": "bundled"})
            )._resolve_cloud_model_name(),
            "minimax/minimax-m2.5",
        )
        self.assertEqual(
            LLMClient(
                Config(model={"name": "moonshotai/kimi-k2.6", "source_kind": "bundled"})
            )._resolve_cloud_model_name(),
            "moonshotai/kimi-k2.6",
        )

    async def test_cloud_chat_completion_retries_transient_provider_failure(self) -> None:
        captured: list[dict] = []
        config = self._bundled_config()
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

    async def test_cloud_chat_completion_preserves_usage_summary_quotas(self) -> None:
        captured: list[dict] = []
        config = self._bundled_config()
        client = LLMClient(config)
        session = type(
            "CloudSessionStub",
            (),
            {"api_url": "http://127.0.0.1:4000", "access_token": "token"},
        )()
        quotas = {"fiveHour": {"usedUsdCents": 0.5, "capUsdCents": 100}}
        responses: list[object] = [
            _FakeResponse(
                stream_events=[
                    {
                        "type": "message_complete",
                        "finishReason": "stop",
                        "usage": {
                            "promptTokens": 10,
                            "completionTokens": 2,
                            "totalTokens": 12,
                        },
                        "quotas": quotas,
                    }
                ]
            )
        ]

        def _fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(capture=captured, responses=responses)

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

        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)
        self.assertEqual(events[-1].usage_summary, {"quotas": quotas})

    async def test_cloud_complete_text_retries_transient_connection_error(self) -> None:
        captured: list[dict] = []
        config = self._bundled_config()
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
        config = self._bundled_config()
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
        self.assertEqual(client.config.model.source_kind, "saved")

    async def test_cloud_complete_text_falls_back_to_saved_provider_on_entitlement_denied(self) -> None:
        captured: list[dict] = []
        config = self._bundled_config()
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
        self.assertEqual(client.config.model.source_kind, "saved")

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

    async def test_stream_response_captures_reasoning_content_for_replay(self) -> None:
        chunks = _AsyncChunks(
            [
                _Obj(
                    usage=None,
                    choices=[
                        _Obj(
                            finish_reason=None,
                            delta=_Obj(
                                content=None,
                                reasoning_content="look up the date",
                                tool_calls=None,
                            ),
                        )
                    ],
                ),
                _Obj(
                    usage=None,
                    choices=[
                        _Obj(
                            finish_reason="tool_calls",
                            delta=_Obj(
                                content="I will check.",
                                reasoning_content=None,
                                tool_calls=None,
                            ),
                        )
                    ],
                ),
            ]
        )
        client = LLMClient(self._config())

        events = [
            event
            async for event in client._stream_response(
                _FakeOpenAIClient(chunks),
                {"model": "deepseek-v4-pro", "messages": [], "stream": True},
            )
        ]

        self.assertEqual(events[-1].type, StreamEventType.MESSAGE_COMPLETE)
        self.assertEqual(events[-1].reasoning_content, "look up the date")

    def test_sanitize_messages_preserves_deepseek_v4_reasoning_content(self) -> None:
        client = LLMClient(
            Config(
                model={"name": "deepseek-v4-pro"},
                api_key="sk-test",
                base_url="https://api.deepseek.com",
            )
        )

        sanitized = client._sanitize_messages(
            [
                {
                    "role": "assistant",
                    "content": "I will check.",
                    "reasoning_content": "I need a tool result.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }
                    ],
                }
            ]
        )

        self.assertEqual(sanitized[0]["reasoning_content"], "I need a tool result.")

    def test_sanitize_messages_omits_reasoning_content_for_other_providers(self) -> None:
        client = LLMClient(
            Config(
                model={"name": "gpt-5.4"},
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
            )
        )

        sanitized = client._sanitize_messages(
            [
                {
                    "role": "assistant",
                    "content": "I will check.",
                    "reasoning_content": "provider-private reasoning",
                }
            ]
        )

        self.assertNotIn("reasoning_content", sanitized[0])


if __name__ == "__main__":
    unittest.main()
