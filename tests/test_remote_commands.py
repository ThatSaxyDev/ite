from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from ite.remote.commands import is_slash_command, parse_command, run_headless_command
from ite.remote.host import HeadlessRuntimeHost


class _StubSession:
    """Records the state changes a command handler makes."""

    def __init__(self) -> None:
        self.plan_mode_enabled = False
        self.plan_phase = "idle"
        self.plan_questions_asked = 0
        self.session_id = "stub-session"
        self.calls: list[tuple[str, Any]] = []

    def set_plan_mode(self, enabled: bool) -> None:
        self.calls.append(("set_plan_mode", enabled))
        self.plan_mode_enabled = enabled

    def set_plan_phase(self, phase: str) -> None:
        self.calls.append(("set_plan_phase", phase))
        self.plan_phase = phase

    def has_pending_plan(self) -> bool:
        return False

    def has_active_plan(self) -> bool:
        return False

    def current_plan_text(self) -> str:
        return ""


class _StubAgent:
    def __init__(self, session: _StubSession) -> None:
        self.session = session
        self.run_calls: list[str] = []


class SlashCommandDetectionTests(unittest.TestCase):
    def test_commands_are_recognised(self) -> None:
        for text in ["/plan", "/plan on", "/approval yolo", "/stats"]:
            self.assertTrue(is_slash_command(text), text)

    def test_plain_prompts_are_not_commands(self) -> None:
        for text in ["hello", "what is /plan", "/", "//comment", ""]:
            self.assertFalse(is_slash_command(text), text)

    def test_parsing_matches_the_tui(self) -> None:
        self.assertEqual(parse_command("/plan on"), ("/plan", ["on"]))
        self.assertEqual(parse_command("/STATS"), ("/stats", []))
        self.assertEqual(parse_command("/model gpt-4"), ("/model", ["gpt-4"]))


class HeadlessCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_on_changes_session_state(self) -> None:
        session = _StubSession()
        agent = _StubAgent(session)

        result = await run_headless_command(
            command_line="/plan on",
            config=None,
            agent=agent,
            cwd=Path("/tmp"),
        )

        self.assertTrue(result.ok, result.error)
        # The whole point: the command mutates state instead of being sent to
        # the model as the literal text "plan on".
        self.assertIn(("set_plan_mode", True), session.calls)
        self.assertTrue(session.plan_mode_enabled)
        self.assertIn("Plan mode is now", result.output)
        self.assertEqual(agent.run_calls, [])

    async def test_plan_status_reports_without_side_effects(self) -> None:
        session = _StubSession()
        agent = _StubAgent(session)

        result = await run_headless_command(
            command_line="/plan",
            config=None,
            agent=agent,
            cwd=Path("/tmp"),
        )

        self.assertTrue(result.ok, result.error)
        self.assertIn("Status:", result.output)
        self.assertEqual(session.calls, [])

    async def test_unknown_command_is_reported_not_run(self) -> None:
        session = _StubSession()
        result = await run_headless_command(
            command_line="/definitely_not_a_command",
            config=None,
            agent=_StubAgent(session),
            cwd=Path("/tmp"),
        )

        self.assertFalse(result.ok)
        self.assertIn("Unknown command", result.error)

    async def test_ui_only_command_is_honest_about_availability(self) -> None:
        session = _StubSession()
        result = await run_headless_command(
            command_line="/theme",
            config=None,
            agent=_StubAgent(session),
            cwd=Path("/tmp"),
        )

        # Better to say so than to silently do nothing.
        self.assertFalse(result.ok)
        self.assertIn("isn't available", result.error)

    async def test_picker_command_requests_a_remote_modal(self) -> None:
        session = _StubSession()

        result = await run_headless_command(
            command_line="/models",
            config=None,
            agent=_StubAgent(session),
            cwd=Path("/tmp"),
        )

        # `/models` delegates to a picker the runtime cannot render. It must
        # surface that as a UI request rather than failing or doing nothing.
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.ui_request, "model_picker")

    async def test_thread_commands_are_honest_about_availability(self) -> None:
        session = _StubSession()

        # The cloud runtime is single-session, so thread management cannot be
        # honoured. Requesting a UI the app cannot fulfil would be worse than
        # saying so plainly.
        for command in ["/new", "/close"]:
            result = await run_headless_command(
                command_line=command,
                config=None,
                agent=_StubAgent(session),
                cwd=Path("/tmp"),
            )
            self.assertFalse(result.ok, command)
            self.assertIn("isn't available", result.error)
            self.assertEqual(result.ui_request, "")

    async def test_command_failure_does_not_raise(self) -> None:
        class _Broken:
            session = _StubSession()

            def __getattr__(self, name: str) -> Any:
                raise AssertionError("agent should not be run for a command")

        broken = _Broken()
        broken.session.set_plan_mode = lambda *_: (_ for _ in ()).throw(  # type: ignore[method-assign]
            RuntimeError("boom")
        )

        result = await run_headless_command(
            command_line="/plan on",
            config=None,
            agent=broken,
            cwd=Path("/tmp"),
        )

        # A failing command surfaces as a failed result, never as a crash.
        self.assertFalse(result.ok)
        self.assertIn("boom", result.error)


class SubmitPromptRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_command_does_not_start_a_model_turn(self) -> None:
        session = _StubSession()
        agent = _StubAgent(session)

        host = HeadlessRuntimeHost(config=None, cwd=Path("/tmp"))  # type: ignore[arg-type]
        host._agent = agent  # type: ignore[attr-defined]
        host._session = session  # type: ignore[attr-defined]

        await host.submit_prompt("/plan on")
        # Let the queued command task finish.
        assert host._command_task is not None  # type: ignore[attr-defined]
        await host._command_task  # type: ignore[attr-defined]

        self.assertTrue(session.plan_mode_enabled)
        self.assertEqual(agent.run_calls, [])
        # The command shows up in the feed so the app can render it.
        self.assertEqual(len(host._command_feed), 1)  # type: ignore[attr-defined]
        entry = host._command_feed[0]  # type: ignore[attr-defined]
        self.assertEqual(entry["command"], "/plan on")
        self.assertEqual(entry["status"], "completed")

    async def test_plain_prompt_is_still_a_turn(self) -> None:
        session = _StubSession()
        agent = _StubAgent(session)

        host = HeadlessRuntimeHost(config=None, cwd=Path("/tmp"))  # type: ignore[arg-type]
        host._agent = agent  # type: ignore[attr-defined]
        host._session = session  # type: ignore[attr-defined]

        started: list[str] = []

        async def _fake_start_turn(message: str) -> None:
            started.append(message)

        host._start_turn = _fake_start_turn  # type: ignore[method-assign]

        await host.submit_prompt("hello there")

        self.assertEqual(started, ["hello there"])
        self.assertEqual(host._command_feed, [])  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
