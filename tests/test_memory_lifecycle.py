import asyncio
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from rich.console import Console

from ite.agent.agent import Agent
from ite.agent.session import Session
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage, ToolCall
from ite.commands import CommandContext
from ite.commands.session import cmd_compact, cmd_save
from ite.config.config import Config
from ite.memory.session_memory import SessionMemoryManager
from ite.tools.base import ToolResult


class _DummyTUI:
    pass


class MemoryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        patcher_memory = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher_session_memory = patch(
            "ite.memory.session_memory.get_data_dir",
            return_value=self.base_path,
        )
        patcher_compact_artifacts = patch(
            "ite.context.compact_artifacts.get_data_dir",
            return_value=self.base_path,
        )
        patcher_memory.start()
        patcher_session_memory.start()
        patcher_compact_artifacts.start()
        self.addCleanup(patcher_memory.stop)
        self.addCleanup(patcher_session_memory.stop)
        self.addCleanup(patcher_compact_artifacts.stop)

    async def test_cmd_save_records_workspace_scoped_episode(self) -> None:
        workspace = self.base_path / "ws-save"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.context_manager.add_user_message("hello")
        agent.session.turn_count = 1

        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=_DummyTUI(),
            console=Console(file=StringIO()),
        )

        with patch("ite.agent.session_manager.get_data_dir", return_value=self.base_path):
            await cmd_save(ctx, [])

        episodes = agent.session.memory_manager.list_episodes()
        self.assertTrue(any("Session saved (1 turns): hello" in ep["summary"] for ep in episodes))

    async def test_session_initialize_is_not_degraded_when_dependencies_are_available(self) -> None:
        workspace = self.base_path / "ws-healthy-startup"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        self.assertFalse(agent.session.is_degraded())
        self.assertEqual(agent.session.runtime_status.disabled_capabilities, [])
        self.assertEqual(agent.session.runtime_summary(), "")

    async def test_context_compaction_records_episode(self) -> None:
        workspace = self.base_path / "ws-compact"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = lambda: True  # type: ignore[method-assign]

        events = []
        async for event in agent.run("trigger compaction"):
            events.append(event)

        self.assertTrue(any(event.type == AgentEventType.CONTEXT_COMPACTED for event in events))
        compacted_event = next(event for event in events if event.type == AgentEventType.CONTEXT_COMPACTED)
        self.assertEqual(compacted_event.data.get("trigger_reason"), "threshold")
        episodes = session.memory_manager.list_episodes()
        self.assertTrue(
            any(
                "Context compacted after" in ep["summary"]
                and "trigger compaction" in ep["summary"]
                for ep in episodes
            )
        )

    async def test_auto_compaction_starts_fresh_turn_after_boundary(self) -> None:
        workspace = self.base_path / "ws-auto-compact-boundary"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        needs_sequence = iter([True, False])
        call_turn_counts: list[int] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            call_turn_counts.append(session.turn_count)
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Continued after compaction."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = (  # type: ignore[method-assign]
            lambda: next(needs_sequence, False)
        )

        events = []
        async for event in agent.run("trigger compaction boundary"):
            events.append(event)

        self.assertEqual(call_turn_counts, [])
        self.assertEqual(session.turn_count, 0)
        compacted_index = next(
            idx
            for idx, event in enumerate(events)
            if event.type == AgentEventType.CONTEXT_COMPACTED
        )
        self.assertTrue(events[compacted_index].data.get("auto_resume_required"))
        self.assertFalse(any(event.type == AgentEventType.TEXT_COMPLETE for event in events))

    async def test_auto_compaction_waits_before_continuation(self) -> None:
        workspace = self.base_path / "ws-compact-delay"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        needs_sequence = iter([True, False])
        call_turn_counts: list[int] = []
        sleep_calls: list[float] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            call_turn_counts.append(session.turn_count)
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Continued after delay."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = (  # type: ignore[method-assign]
            lambda: next(needs_sequence, False)
        )

        with patch("ite.agent.agent.asyncio.sleep", side_effect=fake_sleep):
            events = []
            async for event in agent.run("trigger delayed compaction boundary"):
                events.append(event)

        self.assertEqual(call_turn_counts, [1])
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(
            sleep_calls[0],
            Agent.POST_COMPACTION_CONTINUATION_DELAY_SECONDS,
        )
        self.assertTrue(any(event.type == AgentEventType.CONTEXT_COMPACTED for event in events))

    async def test_post_compaction_transient_failure_recovers_in_place(self) -> None:
        workspace = self.base_path / "ws-post-compact-retry"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        needs_sequence = iter([True, False, False])
        call_count = 0
        sleep_calls: list[float] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=(
                        "Bundled inference provider failed (ollama-dev) with status 503. "
                        'Provider request failed (503): {"error":"Service Temporarily Unavailable"}'
                    ),
                )
                return
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Recovered after compaction."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = (  # type: ignore[method-assign]
            lambda: next(needs_sequence, False)
        )

        with patch("ite.agent.agent.asyncio.sleep", side_effect=fake_sleep):
            events = []
            async for event in agent.run("trigger post-compact recovery"):
                events.append(event)

        self.assertEqual(call_count, 2)
        self.assertEqual(
            sleep_calls,
            [Agent.POST_COMPACTION_CONTINUATION_DELAY_SECONDS, 1.0],
        )
        self.assertTrue(any(event.type == AgentEventType.CONTEXT_COMPACTED for event in events))
        self.assertTrue(any(event.type == AgentEventType.TEXT_COMPLETE for event in events))
        self.assertFalse(any(event.type == AgentEventType.AGENT_ERROR for event in events))

    async def test_post_compaction_continuation_injects_continue_prompt(self) -> None:
        workspace = self.base_path / "ws-post-compact-continue-prompt"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        needs_sequence = iter([True, False])
        outbound_payloads: list[list[dict]] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            outbound_payloads.append(messages)
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Resumed."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        async def fake_sleep(delay: float) -> None:
            return None

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = (  # type: ignore[method-assign]
            lambda: next(needs_sequence, False)
        )

        with patch("ite.agent.agent.asyncio.sleep", side_effect=fake_sleep):
            async for _event in agent.run("trigger continue prompt"):
                pass

        self.assertEqual(len(outbound_payloads), 1)
        self.assertEqual(
            outbound_payloads[0][-1],
            {
                "role": "user",
                "content": Agent.POST_COMPACTION_CONTINUE_PROMPT,
            },
        )

    async def test_post_compaction_recovery_stays_active_across_tool_loop(self) -> None:
        workspace = self.base_path / "ws-post-compact-tool-loop"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        needs_sequence = iter([True, False, False, False])
        call_count = 0
        sleep_calls: list[float] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta("Let me continue by reading the implementation."),
                )
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ToolCall(
                        call_id="call_1",
                        name="read_file",
                        arguments={"path": "src/ite/context/manager.py"},
                    ),
                )
                yield StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
                return
            if call_count == 2:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=(
                        "Bundled inference provider failed (ollama-dev) with status 503. "
                        'Provider request failed (503): {"error":"Service Temporarily Unavailable"}'
                    ),
                )
                return
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Recovered after tool loop."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def fake_invoke(*args, **kwargs):
            return ToolResult.success_result("Read complete.")

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = (  # type: ignore[method-assign]
            lambda: next(needs_sequence, False)
        )
        session.tool_registry.get = lambda _name: SimpleNamespace(  # type: ignore[method-assign]
            validate_params=lambda _params: []
        )
        session.tool_registry.invoke = fake_invoke  # type: ignore[method-assign]

        with patch("ite.agent.agent.asyncio.sleep", side_effect=fake_sleep):
            events = []
            async for event in agent.run("trigger post-compact tool recovery"):
                events.append(event)

        self.assertEqual(call_count, 3)
        self.assertEqual(
            sleep_calls,
            [Agent.POST_COMPACTION_CONTINUATION_DELAY_SECONDS, 1.0],
        )
        self.assertTrue(any(event.type == AgentEventType.CONTEXT_COMPACTED for event in events))
        self.assertTrue(any(event.type == AgentEventType.TEXT_COMPLETE for event in events))
        self.assertFalse(any(event.type == AgentEventType.AGENT_ERROR for event in events))

    async def test_tool_bound_prelude_is_not_rendered_as_final_message(self) -> None:
        workspace = self.base_path / "ws-tool-bound-prelude"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta("Let me verify each claim systematically by reading the actual implementation files."),
                )
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ToolCall(
                        call_id="call_1",
                        name="read_file",
                        arguments={"path": "src/ite/context/manager.py"},
                    ),
                )
                yield StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
                return
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Here is the complete comparison."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_invoke(*args, **kwargs):
            return ToolResult.success_result("Read complete.")

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.tool_registry.get = lambda _name: SimpleNamespace(  # type: ignore[method-assign]
            validate_params=lambda _params: []
        )
        session.tool_registry.invoke = fake_invoke  # type: ignore[method-assign]

        events = []
        async for event in agent.run("compare iTE and csrc"):
            events.append(event)

        completed_texts = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]
        self.assertEqual(completed_texts, ["Here is the complete comparison."])

    async def test_context_overflow_retries_after_compaction(self) -> None:
        workspace = self.base_path / "ws-overflow-retry"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=(
                        "The model provider returned an API error.\n"
                        "- Status: 400\n"
                        "- prompt too long; exceeded max context length by 1397 tokens"
                    ),
                )
                return
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Recovered."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\ncontinue", TokenUsage(total_tokens=10)

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]

        events = []
        async for event in agent.run("trigger overflow retry"):
            events.append(event)

        self.assertEqual(call_count, 2)
        self.assertTrue(any(event.type == AgentEventType.CONTEXT_COMPACTED for event in events))
        compacted_event = next(event for event in events if event.type == AgentEventType.CONTEXT_COMPACTED)
        self.assertEqual(compacted_event.data.get("trigger_reason"), "overflow_retry")
        self.assertTrue(any(event.type == AgentEventType.TEXT_COMPLETE for event in events))

    async def test_context_restore_summary_warns_against_git_write_actions(self) -> None:
        workspace = self.base_path / "ws-restore-summary"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        agent.session.context_manager.replace_with_summary("## ORIGINAL GOAL\ncontinue")

        messages = agent.session.context_manager.get_messages()
        content = "\n".join(str(message.get("content", "")) for message in messages)
        self.assertIn("Do not perform git write actions", content)
        self.assertIn("wait for user confirmation instead", content)

    async def test_snapshot_generation_writes_structured_session_memory(self) -> None:
        workspace = self.base_path / "ws-session-memory"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.set_manual_name("Memory foundation")
        session.context_manager.add_user_message("Refactor context compaction to use boundaries.")
        session.context_manager.add_assistant_message("I will inspect the context and persistence layers.")

        snapshot = session.snapshot_kwargs(workspace_path=str(workspace.resolve()))

        self.assertEqual(snapshot["session_id"], session.session_id)
        content = SessionMemoryManager(workspace, session_id=session.session_id).get_content()
        assert content is not None
        self.assertIn("# Session Title", content)
        self.assertIn("Memory foundation", content)
        self.assertIn("# Current State", content)
        self.assertIn("# Task Specification", content)
        self.assertIn("Refactor context compaction to use boundaries", content)

    async def test_system_prompt_includes_session_memory_when_available(self) -> None:
        workspace = self.base_path / "ws-session-memory-prompt"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.set_manual_name("Prompt continuity")
        session.context_manager.add_user_message("Audit the session continuity model.")
        session.snapshot_kwargs(workspace_path=str(workspace.resolve()))

        messages = session.context_manager.get_messages()
        system_prompt = messages[0]["content"]

        self.assertIn("# Current Session Memory", system_prompt)
        self.assertIn("Prompt continuity", system_prompt)
        self.assertIn("Audit the session continuity model", system_prompt)

    async def test_manual_compact_command_runs_compaction_pipeline(self) -> None:
        workspace = self.base_path / "ws-manual-compact"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(4):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nmanual compact", TokenUsage(total_tokens=7)

        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]

        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=_DummyTUI(),
            console=Console(file=StringIO()),
        )

        await cmd_compact(ctx, [])

        snapshot_messages = session.context_manager.get_snapshot_messages()
        boundary = next(
            (
                item
                for item in snapshot_messages
                if item.get("role") == "system" and item.get("subtype") == "compact_boundary"
            ),
            None,
        )
        self.assertIsNotNone(boundary)
        assert boundary is not None
        self.assertEqual(boundary.get("metadata", {}).get("trigger_reason"), "manual")
        self.assertTrue(
            session.compact_artifact_manager.load_summary(
                boundary.get("metadata", {}).get("summary_artifact_id")
            )
        )
        live_messages = session.context_manager.get_messages()
        self.assertTrue(
            any(
                msg.get("role") == "system"
                and str(msg.get("content", "")).startswith(
                    "Compaction summary artifact loaded for live continuation."
                )
                for msg in live_messages
            )
        )
        self.assertFalse(
            any(
                str(msg.get("content", "")).startswith(
                    "# Context Restoration (Previous Session Compacted)"
                )
                for msg in live_messages
            )
        )
        episodes = session.memory_manager.list_episodes()
        self.assertTrue(
            any("Context compacted manually for testing" in ep["summary"] for ep in episodes)
        )

    async def test_compact_status_reports_thresholds(self) -> None:
        workspace = self.base_path / "ws-compact-status"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.context_manager.add_user_message("short test message")

        output = StringIO()
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=_DummyTUI(),
            console=Console(file=output),
        )

        await cmd_compact(ctx, ["status"])

        rendered = output.getvalue()
        self.assertIn("Compaction status", rendered)
        self.assertIn("Current tokens", rendered)
        self.assertIn("Trigger at", rendered)

    async def test_manual_compact_command_works_after_resume(self) -> None:
        workspace = self.base_path / "ws-manual-compact-resume"
        workspace.mkdir()

        original = Session(Config(cwd=workspace, api_key="test"))
        await original.initialize()
        original.context_manager.add_user_message("Resume this thread and compact it.")
        original.context_manager.add_assistant_message("I will continue after restore.")

        snapshot = original.snapshot_kwargs(workspace_path=str(workspace.resolve()))

        resumed = Session(Config(cwd=workspace, api_key="test"))
        resumed.set_session_id(snapshot["session_id"])
        await resumed.initialize()
        resumed.context_manager.restore_transcript_state(snapshot["transcript_state"])

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nresume-aware compact", TokenUsage(total_tokens=9)

        resumed.chat_compactor.compact = fake_compact  # type: ignore[method-assign]

        agent = Agent(Config(cwd=workspace, api_key="test"))
        agent.session = resumed
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=_DummyTUI(),
            console=Console(file=StringIO()),
        )

        await cmd_compact(ctx, [])

        snapshot_messages = resumed.context_manager.get_snapshot_messages()
        boundary = next(
            (
                item
                for item in snapshot_messages
                if item.get("role") == "system" and item.get("subtype") == "compact_boundary"
            ),
            None,
        )
        self.assertIsNotNone(boundary)
        assert boundary is not None
        self.assertEqual(boundary.get("metadata", {}).get("trigger_reason"), "manual")

    async def test_snapshot_transcript_state_preserves_compacted_history_on_restore(self) -> None:
        workspace = self.base_path / "ws-transcript-restore"
        workspace.mkdir()

        original = Session(Config(cwd=workspace, api_key="test"))
        await original.initialize()
        original.context_manager.add_user_message("phase A instruction")
        original.context_manager.add_assistant_message("phase A response")
        original.context_manager.add_user_message("phase B instruction")
        original.context_manager.add_assistant_message("phase B response")
        original.context_manager.replace_with_summary(
            "## ORIGINAL GOAL\ncontinue with phase B",
            boundary_metadata={
                "trigger_reason": "manual",
                "summary_artifact_id": "artifact-restore",
            },
            preserved_messages=original.context_manager.select_compaction_tail(max_messages=2),
        )

        snapshot = original.snapshot_kwargs(workspace_path=str(workspace.resolve()))

        restored = Session(Config(cwd=workspace, api_key="test"))
        restored.set_session_id(snapshot["session_id"])
        await restored.initialize()
        restored.context_manager.restore_transcript_state(snapshot["transcript_state"])

        transcript_events = restored.context_manager.get_transcript_events()
        self.assertTrue(any(event["kind"] == "compact_boundary" for event in transcript_events))
        self.assertTrue(any(event.get("role") == "user" for event in transcript_events))

        active_contents = [
            str(message.get("content", ""))
            for message in restored.context_manager.get_messages()
        ]
        self.assertFalse(any("phase A instruction" in content for content in active_contents))
        self.assertTrue(any("phase B response" in content for content in active_contents))

    async def test_compaction_preserves_recent_raw_tail_messages(self) -> None:
        workspace = self.base_path / "ws-compaction-tail"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        session.context_manager.replace_with_summary(
            "## ORIGINAL GOAL\ncontinue",
            boundary_metadata={"trigger_reason": "threshold"},
            preserved_messages=session.context_manager.select_compaction_tail(max_messages=4),
        )

        snapshot_messages = session.context_manager.get_snapshot_messages()
        contents = [str(item.get("content", "")) for item in snapshot_messages]

        self.assertTrue(any("assistant message 7" in content for content in contents))
        self.assertTrue(any("user message 7" in content for content in contents))

    async def test_restore_uses_compact_artifact_when_boundary_metadata_is_present(self) -> None:
        workspace = self.base_path / "ws-compact-artifact"
        workspace.mkdir()

        session = Session(Config(cwd=workspace, api_key="test"))
        await session.initialize()
        artifact_id = session.compact_artifact_manager.save_summary(
            "## ORIGINAL GOAL\nUse artifact-backed restoration."
        )

        snapshot_messages = [
            {
                "role": "system",
                "content": "Context compacted; earlier history replaced with continuation summary.",
                "subtype": "compact_boundary",
                "metadata": {"summary_artifact_id": artifact_id},
            },
            {
                "role": "user",
                "content": "# Context Restoration (Previous Session Compacted)\n\nplaceholder",
            },
            {
                "role": "assistant",
                "content": "I've reviewed the context from the previous session. I understand:\n- placeholder",
            },
            {
                "role": "user",
                "content": "Continue with the REMAINING work only. Do NOT repeat any completed actions.",
            },
            {
                "role": "user",
                "content": "Latest request after compaction.",
            },
        ]

        restored = Session(Config(cwd=workspace, api_key="test"))
        await restored.initialize()
        restored.context_manager.set_messages(snapshot_messages)
        messages = restored.context_manager.get_messages()

        self.assertTrue(
            any(
                msg.get("role") == "system"
                and "artifact-backed restoration"
                in str(msg.get("content", "")).lower()
                for msg in messages
            )
        )
        self.assertFalse(
            any(
                str(msg.get("content", "")).startswith(
                    "# Context Restoration (Previous Session Compacted)"
                )
                for msg in messages
            )
        )

    async def test_low_value_exit_prompt_is_not_used_as_focus(self) -> None:
        workspace = self.base_path / "ws-low-value-focus"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.context_manager.add_user_message("How do I like my responses?")

        summary = session.build_lifecycle_summary("Session exited")
        self.assertEqual(summary, "Session exited")

    async def test_session_initialize_degrades_when_memory_persistence_fails(self) -> None:
        workspace = self.base_path / "ws-degraded-startup"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None

        with patch(
            "ite.memory.manager.MemoryManager._memory_root",
            side_effect=PermissionError("storage unavailable"),
        ):
            await agent.session.initialize()

        session = agent.session
        self.assertTrue(session.is_degraded())
        self.assertIn("persistent_memory", session.runtime_status.disabled_capabilities)
        self.assertIsNotNone(session.context_manager)
        self.assertIn("persistent memory unavailable", session.runtime_summary().lower())

    async def test_session_initialize_degrades_when_mcp_fails(self) -> None:
        workspace = self.base_path / "ws-mcp-failure"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None

        with patch.object(
            agent.session.mcp_manager,
            "initialize",
            side_effect=RuntimeError("mcp boot failed"),
        ):
            await agent.session.initialize()

        session = agent.session
        self.assertTrue(session.is_degraded())
        self.assertIn("mcp", session.runtime_status.disabled_capabilities)
        self.assertIsNotNone(session.context_manager)
        self.assertIn("mcp unavailable", session.runtime_summary().lower())

    async def _fake_chat_completion(self, messages, tools=None, stream=True):
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta("Done."),
        )
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


if __name__ == "__main__":
    unittest.main()
