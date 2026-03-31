import unittest
from unittest.mock import patch

from ite.client.llm_client import LLMClient
from ite.config.config import Config


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"ok": True, "output": "hi", "usage": {}}


class _FakeAsyncClient:
    def __init__(self, *, capture: list[dict]) -> None:
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self._capture.append({"url": url, "headers": headers or {}, "json": json or {}})
        return _FakeResponse()


class LLMClientTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(payload["model"], "minimax-m2.7")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("tools", payload)
        self.assertNotIn("toolChoice", payload)


if __name__ == "__main__":
    unittest.main()
