import unittest

from ite.client.response import StreamEvent
from ite.client.response import StreamEventType
from ite.client.response import TextDelta
from ite.client.response import TokenUsage
from ite.config.config import Config
from ite.context.compaction import ChatCompactor
from ite.context.manager import ContextManager


class _FakeClient:
    def __init__(self, events):
        self._events = list(events)

    async def chat_completion(self, messages, tools=None, stream=True):
        for event in self._events:
            yield event


class CompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_compact_collects_summary_from_cloud_style_text_delta(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("Investigate compaction failure.")
        context.add_assistant_message("I am checking the provider event path.")

        client = _FakeClient(
            [
                StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta("## ORIGINAL GOAL\n"),
                ),
                StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta("Resume from the compaction boundary."),
                ),
                StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                ),
            ]
        )

        summary, usage = await ChatCompactor(client).compact(context)  # type: ignore[arg-type]

        self.assertEqual(
            summary,
            "## ORIGINAL GOAL\nResume from the compaction boundary.",
        )
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage.total_tokens, 15)

    async def test_compact_records_provider_error_event(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("Investigate compaction failure.")
        context.add_assistant_message("I am checking the provider event path.")

        client = _FakeClient(
            [
                StreamEvent(
                    type=StreamEventType.ERROR,
                    error="Cloud session is missing or expired.",
                ),
            ]
        )

        compactor = ChatCompactor(client)  # type: ignore[arg-type]
        summary, usage = await compactor.compact(context)

        self.assertIsNone(summary)
        self.assertIsNone(usage)
        self.assertEqual(compactor.last_error, "Cloud session is missing or expired.")


if __name__ == "__main__":
    unittest.main()
