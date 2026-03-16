import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.agent.session import Session
from ite.config.config import Config
from ite.context.manager import ContextManager
from ite.memory import (
    extract_conditional_preference_instructions,
    extract_preference_controls,
    is_memory_probe,
    parse_explicit_memory_instructions,
    parse_explicit_memory_instruction,
    resolve_response_intent,
    should_reject_durable_memory_capture,
)
from ite.memory.manager import MemoryManager
from ite.tools.base import ToolInvocation
from ite.tools.builtin.memory import MemoryTool


class MemoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)

        patcher = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_short_term_is_session_scoped(self) -> None:
        workspace = self.base_path / "ws"
        workspace.mkdir()

        first = MemoryManager(workspace, session_id="session-a")
        second = MemoryManager(workspace, session_id="session-b")

        first.set_entry("short_term", "focus", "memory redesign", source="test")

        self.assertEqual(len(first.list_entries("short_term")), 1)
        self.assertEqual(second.list_entries("short_term"), [])

    def test_episodic_is_workspace_scoped(self) -> None:
        workspace_a = self.base_path / "ws-a"
        workspace_b = self.base_path / "ws-b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        manager_a = MemoryManager(workspace_a, session_id="a")
        manager_b = MemoryManager(workspace_b, session_id="b")

        manager_a.append_episode("Decided to use scoped episodic memory", source="test")

        self.assertEqual(len(manager_a.list_episodes()), 1)
        self.assertEqual(manager_b.list_episodes(), [])

    def test_prompt_memory_prefers_relevant_semantic_entries(self) -> None:
        workspace = self.base_path / "ws"
        workspace.mkdir()

        manager = MemoryManager(workspace, session_id="session-a")
        manager.set_entry("semantic", "tests", "Use pytest for test execution", source="test")
        manager.set_entry("semantic", "lint", "Use ruff for linting", source="test")
        manager.set_entry("long_term", "style", "Keep answers concise", source="test")

        bundle = manager.load_prompt_memory("What tests should we run here?")

        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertIn("tests", bundle["semantic"])
        self.assertLessEqual(
            sum(len(bundle[store]) for store in ("short_term", "long_term", "semantic"))
            + len(bundle["episodic"]),
            5,
        )

    def test_context_manager_reads_memory_live_each_turn(self) -> None:
        workspace = self.base_path / "ws"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")
        config = Config(cwd=workspace)

        context_manager = ContextManager(
            config=config,
            tools=[],
            memory_provider=manager.load_prompt_memory,
        )
        context_manager.add_user_message("Explain the architecture and include paths.")

        manager.set_entry(
            "long_term",
            "file_paths",
            "Use absolute file paths in explanations",
            source="test",
        )

        messages = context_manager.get_messages()
        system_prompt = messages[0]["content"]

        self.assertIn("# Active Response Controls", system_prompt)
        self.assertIn("absolute file paths", system_prompt.lower())

    def test_newer_preference_controls_override_older_ones(self) -> None:
        workspace = self.base_path / "ws-controls"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")

        manager.set_entry(
            "long_term",
            "pref_short",
            "Keep answers short and avoid bullet lists",
            source="test",
        )
        manager.set_entry(
            "long_term",
            "pref_detailed",
            "Give detailed answers with bullet lists when helpful",
            source="test",
        )

        bundle = manager.load_prompt_memory("Explain the architecture of this repo.")

        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle["controls"]["answer_length"], "detailed")
        self.assertEqual(bundle["controls"]["bullet_style"], "helpful")
        self.assertEqual(bundle["long_term"], {})
        long_term_entries = manager.list_entries("long_term")
        self.assertEqual(len(long_term_entries), 1)
        self.assertEqual(long_term_entries[0]["key"], "pref_detailed")

    def test_preference_superseding_keeps_unrelated_long_term_entries(self) -> None:
        workspace = self.base_path / "ws-controls-mixed"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")

        manager.set_entry(
            "long_term",
            "pref_short",
            "Keep answers short and avoid bullet lists",
            source="test",
        )
        manager.set_entry(
            "long_term",
            "pref_paths",
            "Use absolute file paths in explanations",
            source="test",
        )
        manager.set_entry(
            "long_term",
            "pref_detailed",
            "Give detailed answers with bullet lists when helpful",
            source="test",
        )

        long_term_entries = {record["key"] for record in manager.list_entries("long_term")}
        self.assertEqual(long_term_entries, {"pref_detailed", "pref_paths"})

    def test_conditional_preferences_apply_by_query_context(self) -> None:
        workspace = self.base_path / "ws-conditional"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")

        instructions = parse_explicit_memory_instructions(
            "Remember this preference: for debugging, keep answers short; for architecture, give detailed answers."
        )
        for instruction in instructions:
            manager.set_entry(
                instruction.store,
                instruction.key,
                instruction.value,
                source="test",
                metadata=instruction.metadata,
            )

        debug_bundle = manager.load_prompt_memory(
            "We have a failing auth test. What should I check first?"
        )
        architecture_bundle = manager.load_prompt_memory(
            "Explain the architecture of session and memory handling."
        )

        assert debug_bundle is not None
        assert architecture_bundle is not None
        self.assertEqual(debug_bundle["controls"]["answer_length"], "short")
        self.assertIn("debugging", debug_bundle["controls"]["matched_contexts"])
        self.assertEqual(architecture_bundle["controls"]["answer_length"], "detailed")
        self.assertIn("architecture", architecture_bundle["controls"]["matched_contexts"])

    def test_current_request_detail_intent_overrides_short_default(self) -> None:
        workspace = self.base_path / "ws-request-intent"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")

        manager.set_entry(
            "long_term",
            "pref_short",
            "Keep answers short and avoid bullet lists",
            source="test",
        )

        bundle = manager.load_prompt_memory("Explain what this codebase is about extensively.")

        assert bundle is not None
        self.assertEqual(bundle["controls"]["answer_length"], "detailed")
        self.assertEqual(bundle["controls"]["sources"]["answer_length"], "current request")

    def test_response_intent_resolves_contexts_and_request_controls(self) -> None:
        debug_intent = resolve_response_intent("We have a failing auth test. What should I check first?")
        architecture_intent = resolve_response_intent(
            "Explain what this codebase is about extensively."
        )
        proper_intent = resolve_response_intent(
            "Explain what this codebase is about properly."
        )
        overview_intent = resolve_response_intent(
            "Give me the big picture of this repo."
        )

        self.assertIn("debugging", debug_intent.contexts)
        self.assertEqual(architecture_intent.requested_controls["answer_length"], "detailed")
        self.assertIn("architecture", architecture_intent.contexts)
        self.assertIn("explanation", architecture_intent.contexts)
        self.assertEqual(proper_intent.requested_controls["answer_length"], "detailed")
        self.assertIn("architecture", proper_intent.contexts)
        self.assertIn("architecture", overview_intent.contexts)
        self.assertEqual(overview_intent.requested_controls["answer_length"], "detailed")

    def test_prompt_memory_ignores_polluted_episodic_memory_prompts(self) -> None:
        workspace = self.base_path / "ws-episodic"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")
        manager.append_episode(
            "Session exited (2 turns): For this session only, remember the phrase: mango submarine velvet",
            source="session_exit",
        )

        bundle = manager.load_prompt_memory(
            "What phrase should you remember for this session only?"
        )

        if bundle is None:
            return
        self.assertEqual(bundle["episodic"], [])

    def test_prompt_memory_ignores_low_value_exit_episodes(self) -> None:
        workspace = self.base_path / "ws-low-value-episodic"
        workspace.mkdir()
        manager = MemoryManager(workspace, session_id="session-a")
        manager.append_episode(
            "Session exited (5 turns): how do I like my responses",
            source="session_exit",
        )
        manager.append_episode(
            "Session exited (7 turns): what are tools in this repo?",
            source="session_exit",
        )
        manager.append_episode(
            "Session exited (4 turns): fixed memory scoping and prompt refresh",
            source="session_exit",
        )

        bundle = manager.load_prompt_memory("What did we decide last time?")

        assert bundle is not None
        summaries = [entry["summary"].lower() for entry in bundle["episodic"]]
        self.assertTrue(any("fixed memory scoping" in summary for summary in summaries))
        self.assertFalse(any("how do i like my responses" in summary for summary in summaries))
        self.assertFalse(any("what are tools in this repo" in summary for summary in summaries))

    def test_memory_tool_short_term_follows_session_id(self) -> None:
        workspace = self.base_path / "ws-tool"
        workspace.mkdir()
        config = Config(cwd=workspace, api_key="test")

        async def run() -> None:
            session = Session(config=config)
            await session.initialize()
            tool = session.tool_registry.get("memory")
            self.assertIsInstance(tool, MemoryTool)
            assert isinstance(tool, MemoryTool)

            first_session_id = session.session_id
            result = await tool.execute(
                ToolInvocation(
                    params={
                        "action": "set",
                        "store": "short_term",
                        "key": "phrase",
                        "value": "mango submarine velvet",
                    },
                    cwd=workspace,
                )
            )
            self.assertTrue(result.success)

            session.set_session_id("fresh-session")
            missing = await tool.execute(
                ToolInvocation(
                    params={
                        "action": "get",
                        "store": "short_term",
                        "key": "phrase",
                    },
                    cwd=workspace,
                )
            )
            self.assertIn("Not found", missing.output)

            session.set_session_id(first_session_id)
            found = await tool.execute(
                ToolInvocation(
                    params={
                        "action": "get",
                        "store": "short_term",
                        "key": "phrase",
                    },
                    cwd=workspace,
                )
            )
            self.assertIn("mango submarine velvet", found.output)

        import asyncio

        asyncio.run(run())

    def test_memory_tool_rejects_speculative_durable_memory(self) -> None:
        workspace = self.base_path / "ws-tool-guard"
        workspace.mkdir()
        config = Config(cwd=workspace, api_key="test")

        async def run() -> None:
            session = Session(config=config)
            await session.initialize()
            tool = session.tool_registry.get("memory")
            self.assertIsInstance(tool, MemoryTool)
            assert isinstance(tool, MemoryTool)

            result = await tool.execute(
                ToolInvocation(
                    params={
                        "action": "set",
                        "store": "semantic",
                        "key": "storage",
                        "value": "I'm just thinking out loud, maybe we could use Redis, or maybe not.",
                    },
                    cwd=workspace,
                )
            )
            self.assertTrue(result.success)
            self.assertEqual(result.metadata.get("stored"), False)

            manager = MemoryManager(workspace, session_id=session.session_id)
            self.assertEqual(manager.list_entries("semantic"), [])

        import asyncio

        asyncio.run(run())

    def test_explicit_memory_parser_routes_supported_phrases(self) -> None:
        session_note = parse_explicit_memory_instruction(
            "For this session only, remember the phrase: mango submarine velvet."
        )
        self.assertIsNotNone(session_note)
        assert session_note is not None
        self.assertEqual(session_note.store, "short_term")
        self.assertIn("mango submarine velvet", session_note.value)

        workspace_note = parse_explicit_memory_instruction(
            "Remember this for this workspace: use pytest for tests."
        )
        self.assertIsNotNone(workspace_note)
        assert workspace_note is not None
        self.assertEqual(workspace_note.store, "semantic")

        preference = parse_explicit_memory_instruction(
            "From now on, keep answers short and avoid bullet lists."
        )
        self.assertIsNotNone(preference)
        assert preference is not None
        self.assertEqual(preference.store, "long_term")

        self.assertIsNone(
            parse_explicit_memory_instruction(
                "Do not remember this: I am considering switching to Go."
            )
        )
        self.assertTrue(
            is_memory_probe("What phrase should you remember for this session only?")
        )
        self.assertEqual(
            extract_preference_controls(
                "From now on, keep answers short and avoid bullet lists."
            ),
            {
                "answer_length": "short",
                "bullet_style": "avoid",
            },
        )
        conditional = extract_conditional_preference_instructions(
            "Remember this preference: for debugging, keep answers short; for architecture, give detailed answers."
        )
        self.assertEqual(len(conditional), 2)
        self.assertEqual(conditional[0].key, "preference_debugging")
        self.assertEqual(conditional[1].key, "preference_architecture")
        self.assertTrue(
            should_reject_durable_memory_capture(
                "semantic",
                "I'm just thinking out loud, maybe we could use Redis, or maybe not.",
            )
        )
        self.assertFalse(
            should_reject_durable_memory_capture(
                "semantic",
                "Use pytest for tests.",
            )
        )


if __name__ == "__main__":
    unittest.main()
