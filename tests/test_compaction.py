import json
import unittest

from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config
from ite.context.compaction import ChatCompactor
from ite.context.manager import ContextManager
from ite.utils.text import count_tokens


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
                    usage=TokenUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
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

    async def test_repeated_compaction_includes_previous_summary_and_corrections(
        self,
    ) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("Original task: fix the auth bug. Do not deploy.")
        context.replace_with_summary(
            "Original task: fix auth. User forbids deployment.",
            boundary_metadata={"trigger_reason": "manual"},
        )
        context.add_user_message("Correction: preserve the refresh token too.")
        requests = []

        async def complete(messages, tools=None, stream=True):
            requests.append(messages)
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=TextDelta(
                    "Fix auth and preserve refresh token. Do not deploy."
                ),
            )

        client = _FakeClient([])
        client.chat_completion = complete
        summary, usage = await ChatCompactor(client).compact(context)
        self.assertIsNotNone(summary)
        self.assertIsNone(usage)  # Usage is optional provider telemetry.
        self.assertIn("User forbids deployment", requests[0][1]["content"])
        self.assertIn(
            "Correction: preserve the refresh token", requests[0][1]["content"]
        )

    async def test_oversized_history_is_processed_in_bounded_passes(self) -> None:
        config = Config(cwd=".", api_key="test")
        config.model.context_window = 8000
        context = ContextManager(config)
        text = "original scope " + "token-sized history " * 4000 + " final correction"
        context.add_user_message(text)
        requests = []

        async def complete(messages, tools=None, stream=True):
            requests.append(messages)
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=TextDelta("rolling checkpoint"),
                usage=TokenUsage(total_tokens=7),
            )

        client = _FakeClient([])
        client.chat_completion = complete
        summary, usage = await ChatCompactor(client).compact(context)
        self.assertEqual(summary, "rolling checkpoint")
        self.assertGreater(len(requests), 1)
        self.assertEqual(usage.total_tokens, len(requests) * 7)
        self.assertIn("original scope", requests[0][1]["content"])
        self.assertIn("final correction", requests[-1][1]["content"])
        for request in requests:
            self.assertLess(
                count_tokens(json.dumps(request), config.model_name) + 1600, 8000
            )
        self.assertIn("rolling checkpoint", requests[1][1]["content"])
        self.assertEqual(context.get_snapshot_messages()[0]["content"], text)

    async def test_incomplete_summary_is_rejected_without_changing_context(
        self,
    ) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("Keep the original request.")
        before = context.export_transcript_state()
        client = _FakeClient(
            [
                StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    text_delta=TextDelta("partial"),
                    finish_reason="length",
                )
            ]
        )
        compactor = ChatCompactor(client)
        summary, _ = await compactor.compact(context)
        self.assertIsNone(summary)
        self.assertIn("incomplete", compactor.last_error)
        self.assertEqual(context.export_transcript_state(), before)

    async def test_duplicate_terminal_text_is_not_appended_twice(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("Task")
        client = _FakeClient(
            [
                StreamEvent(
                    type=StreamEventType.TEXT_DELTA, text_delta=TextDelta("checkpoint")
                ),
                StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    text_delta=TextDelta("checkpoint"),
                ),
            ]
        )
        summary, _ = await ChatCompactor(client).compact(context)
        self.assertEqual(summary, "checkpoint")

    def test_multimodal_tool_output_and_empty_assistant_are_supported(self) -> None:
        compactor = ChatCompactor(_FakeClient([]))
        text = compactor._format_history_for_compaction(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "read_image", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content": [
                        {"type": "text", "text": "image result"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,secretblob"},
                        },
                    ],
                },
            ]
        )
        self.assertIn("image result", text)
        self.assertIn("call-1", text)
        self.assertNotIn("secretblob", text)

    def test_tool_result_retains_final_error(self) -> None:
        text = ChatCompactor(_FakeClient([]))._format_history_for_compaction(
            [
                {
                    "role": "tool",
                    "content": "start " + "x" * 10000 + " FINAL FAILURE",
                    "tool_call_id": "call-1",
                },
            ]
        )
        self.assertIn("start", text)
        self.assertIn("FINAL FAILURE", text)
        self.assertIn("omitted", text)

    def test_single_large_message_triggers_compaction_in_small_window(self) -> None:
        config = Config(cwd=".", api_key="test")
        config.model.context_window = 8000
        context = ContextManager(config)
        context.add_user_message("large input " * 5000)
        self.assertGreater(context.get_compaction_status()["trigger_at"], 0)
        self.assertTrue(context.needs_compression())

    def test_prompt_budget_includes_dynamic_tool_schemas(self) -> None:
        schemas = []
        context = ContextManager(
            Config(cwd=".", api_key="test"), tool_schema_provider=lambda: schemas
        )
        before = context.estimate_current_context_tokens()
        schemas.append({"name": "large-tool", "description": "tool schema " * 2000})
        self.assertGreater(context.estimate_current_context_tokens(), before + 3000)

    def test_tail_is_bounded_and_tool_results_keep_their_calls(self) -> None:
        config = Config(cwd=".", api_key="test")
        config.model.context_window = 20000
        context = ContextManager(config)
        context.add_user_message("task")
        context.add_assistant_message(
            "",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        )
        context.add_tool_result("call-1", "large result " * 10000)
        context.add_user_message("latest steering")
        context.replace_with_summary(
            "task checkpoint",
            boundary_metadata={"trigger_reason": "threshold"},
            preserved_messages=context.select_compaction_tail(),
        )
        self.assertLess(
            context.estimate_current_context_tokens(), config.model.context_window * 0.7
        )
        tail = context.get_snapshot_messages()
        ids = {tc["id"] for message in tail for tc in message.get("tool_calls", [])}
        for message in tail:
            if message["role"] == "tool":
                self.assertIn(message["tool_call_id"], ids)
        self.assertEqual(tail[-1]["content"], "latest steering")

    def test_uncompactable_static_context_leaves_transcript_unchanged(self) -> None:
        config = Config(cwd=".", api_key="test")
        config.model.context_window = 8000
        context = ContextManager(
            config,
            tool_schema_provider=lambda: [{"description": "huge schema " * 10000}],
        )
        context.add_user_message("original request")
        before = context.export_transcript_state()
        with self.assertRaisesRegex(ValueError, "cannot free enough"):
            context.replace_with_summary(
                "checkpoint", boundary_metadata={"trigger_reason": "threshold"}
            )
        self.assertEqual(context.export_transcript_state(), before)
        self.assertEqual(context.compaction_count, 0)

    def test_snapshot_summary_survives_without_external_artifact(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("original")
        context.replace_with_summary(
            "Keep original constraints",
            boundary_metadata={"summary_artifact_id": "missing", "compaction_count": 4},
        )
        restored = ContextManager(
            context.config, compact_artifact_provider=lambda _: None
        )
        restored.set_messages(context.get_snapshot_messages())
        self.assertIn(
            "Keep original constraints", json.dumps(restored.get_prompt_messages())
        )
        self.assertEqual(restored.compaction_count, 4)
        self.assertEqual(restored.last_compacted_at, context.last_compacted_at)
        full = ContextManager(context.config)
        full.restore_transcript_state(context.export_transcript_state())
        self.assertEqual(full.compaction_count, 4)
        self.assertEqual(full.last_compacted_at, context.last_compacted_at)

    def test_pruning_retains_raw_output_and_restore_keeps_it_out_of_prompt(
        self,
    ) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.PRUNE_PROTECT_TOKENS = 1
        for index in range(2):
            context.add_user_message(f"task {index}")
            context.add_assistant_message(
                "",
                tool_calls=[
                    {
                        "id": f"call-{index}",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            )
            context.add_tool_result(f"call-{index}", f"original output {index} " * 100)
        before = context.estimate_current_context_tokens()
        self.assertGreater(context.prune_tool_outputs(minimum_tokens=1), 0)
        self.assertLess(context.estimate_current_context_tokens(), before)
        state = context.export_transcript_state()
        self.assertTrue(
            any(
                "original output 0" in str(event["message"])
                for event in state["events"]
            )
        )
        restored = ContextManager(context.config)
        restored.restore_transcript_state(state)
        self.assertNotIn(
            "original output 0", json.dumps(restored.get_prompt_messages())
        )
        self.assertIn(
            "original output 0", json.dumps(restored.export_transcript_state())
        )

    def test_interrupted_tool_cleanup_does_not_erase_compacted_history(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("earlier raw objective")
        context.replace_with_summary(
            "checkpoint", boundary_metadata={"trigger_reason": "manual"}
        )
        context.add_assistant_message(
            "partial progress",
            tool_calls=[
                {"id": "interrupted", "function": {"name": "shell", "arguments": "{}"}}
            ],
        )
        context.add_tool_result("unmatched-result", "partial tool evidence")
        context.add_user_message("user steers after interruption")
        self.assertIn(
            "earlier raw objective", json.dumps(context.export_transcript_state())
        )
        self.assertIn(
            "partial tool evidence", json.dumps(context.export_transcript_state())
        )
        self.assertNotIn(
            "partial tool evidence", json.dumps(context.get_prompt_messages())
        )
        self.assertNotIn("interrupted", json.dumps(context.get_prompt_messages()))
        self.assertIn("partial progress", json.dumps(context.get_prompt_messages()))

    def test_observed_provider_tokens_calibrate_future_pressure(self) -> None:
        context = ContextManager(Config(cwd=".", api_key="test"))
        context.add_user_message("task")
        local = context.estimate_current_context_tokens()
        context.set_latest_usage(TokenUsage(prompt_tokens=local * 2))
        self.assertEqual(context.estimate_current_context_tokens(), local * 2)
        context.add_user_message("additional context " * 100)
        self.assertGreater(context.estimate_current_context_tokens(), local * 2)

    async def test_current_runtime_state_is_included_in_summary_input(self) -> None:
        context = ContextManager(
            Config(cwd=".", api_key="test"),
            continuation_state_provider=lambda: (
                "Plan id approved-plan. Todo verify-build pending. Subagent run-7 running."
            ),
        )
        context.add_user_message("continue")
        requests = []

        async def complete(messages, tools=None, stream=True):
            requests.append(messages)
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=TextDelta("checkpoint"),
            )

        client = _FakeClient([])
        client.chat_completion = complete
        await ChatCompactor(client).compact(context)
        self.assertIn("approved-plan", requests[0][1]["content"])
        context.replace_with_summary(
            "checkpoint", boundary_metadata={"trigger_reason": "manual"}
        )
        self.assertIn("run-7", json.dumps(context.get_prompt_messages()))

    def test_summary_is_not_truncated_by_snapshot_serializer(self) -> None:
        from ite.agent.session_manager import _compact_messages_for_snapshot

        summary = "verified constraint " * 4000 + "final important constraint"
        messages = [
            {"role": "system", "subtype": "compact_artifact", "content": summary}
        ]
        self.assertEqual(
            _compact_messages_for_snapshot(messages)[0]["content"], summary
        )


if __name__ == "__main__":
    unittest.main()
