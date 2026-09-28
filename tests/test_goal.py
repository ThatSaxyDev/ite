from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ite.agent.goal import GoalState, GoalStatus
from ite.agent.session import Session
from ite.agent.session_manager import SessionSnapshot
from ite.client.response import TokenUsage
from ite.tools.base import ToolInvocation
from ite.tools.builtin.goal_outcome import GoalOutcomeTool
from ite.ui.reup._composer import ComposerMixin
from ite.ui.reup.modals import ConfirmModal
from ite.ui.reup.widgets.side_panels import GoalSidePanel
from ite.ui.tool_narrative import activity_title, describe_tool_activity


def _session_with_goal_fields() -> Session:
    session = Session.__new__(Session)
    session.goal_state = None
    session.goal_history = []
    return session


def test_active_elapsed_excludes_paused_time() -> None:
    started = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    goal = GoalState.create("Ship goal mode", now=started)

    goal.pause(now=started + timedelta(seconds=75))

    assert goal.status is GoalStatus.PAUSED
    assert goal.active_elapsed_seconds(now=started + timedelta(hours=3)) == 75


def test_composer_stop_pauses_an_active_goal_before_cancelling_turn() -> None:
    async def run() -> None:
        pause_goal = AsyncMock(return_value=True)
        cancel_turn = AsyncMock()
        app = SimpleNamespace(
            agent=SimpleNamespace(
                session=SimpleNamespace(goal_state=GoalState.create("Pause on stop"))
            ),
            _pause_goal_from_ui=pause_goal,
            cancel_active_turn=cancel_turn,
        )

        await ComposerMixin._stop_turn_from_composer(app)

        pause_goal.assert_awaited_once_with(reason="Paused from the composer.")
        cancel_turn.assert_not_awaited()

    asyncio.run(run())


def test_composer_stop_cancels_normally_without_an_active_goal() -> None:
    async def run() -> None:
        pause_goal = AsyncMock(return_value=True)
        cancel_turn = AsyncMock()
        app = SimpleNamespace(
            agent=SimpleNamespace(session=SimpleNamespace(goal_state=None)),
            _pause_goal_from_ui=pause_goal,
            cancel_active_turn=cancel_turn,
        )

        await ComposerMixin._stop_turn_from_composer(app)

        pause_goal.assert_not_awaited()
        cancel_turn.assert_awaited_once()

    asyncio.run(run())


def test_session_goal_edit_pauses_and_clear_keeps_history() -> None:
    session = _session_with_goal_fields()
    session.create_goal("Implement a durable goal")
    session.pause_goal()
    session.edit_goal("Implement a durable goal panel")
    archived = session.clear_goal()

    assert session.goal_state is None
    assert archived["objective"] == "Implement a durable goal panel"
    assert session.goal_history[-1]["goal_id"] == archived["goal_id"]


def test_active_goal_restores_as_paused_without_counting_offline_time() -> None:
    started = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    state = GoalState.create("Restore safely", now=started)
    saved = state.to_dict(now=started + timedelta(seconds=30))
    session = _session_with_goal_fields()

    session.restore_goal_state(saved)

    assert session.goal_state is not None
    assert session.goal_state.status is GoalStatus.PAUSED
    assert session.goal_state.active_elapsed_seconds() == 30


def test_snapshot_round_trips_goal_fields_and_old_snapshot_defaults() -> None:
    state = GoalState.create("Persist goal")
    snapshot = SessionSnapshot(
        session_id="goal-session",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        turn_count=1,
        messages=[],
        total_usage=TokenUsage(),
        goal_state=state.to_dict(),
        goal_history=[{"goal_id": "older"}],
    )

    restored = SessionSnapshot.from_dict(snapshot.to_dict())
    legacy = SessionSnapshot.from_dict(
        {
            "session_id": "legacy",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "turn_count": 0,
            "messages": [],
            "total_usage": TokenUsage().__dict__,
        }
    )

    assert restored.goal_state is not None
    assert restored.goal_history == [{"goal_id": "older"}]
    assert legacy.goal_state is None
    assert legacy.goal_history == []


def test_goal_outcome_requires_completion_evidence() -> None:
    session = _session_with_goal_fields()
    session.create_goal("Verify completion")
    tool = GoalOutcomeTool(config=None)
    tool.set_session(session)

    async def run() -> tuple[object, object]:
        missing_evidence = await tool.execute(
            ToolInvocation(
                params={"action": "complete", "summary": "Looks finished"},
                cwd=Path("/tmp"),
            )
        )
        completed = await tool.execute(
            ToolInvocation(
                params={
                    "action": "complete",
                    "summary": "Tests passed",
                    "evidence": {"command": "pytest", "result": "passed"},
                },
                cwd=Path("/tmp"),
            )
        )
        return missing_evidence, completed

    missing_evidence, completed = asyncio.run(run())

    assert not missing_evidence.success
    assert completed.success
    assert completed.metadata == {"action": "complete"}
    assert session.goal_state.status is GoalStatus.COMPLETED


def test_goal_outcomes_use_human_readable_tool_copy() -> None:
    assert activity_title(
        "goal_outcome",
        stage="complete",
        success=True,
        metadata={"action": "complete"},
    ) == "Goal completed"
    assert describe_tool_activity(
        "goal_outcome",
        {"action": "complete"},
        stage="complete",
        success=True,
    ) == "Recorded the evidence and completed this goal."


def test_goal_side_panel_renders_active_controls() -> None:
    goal = GoalState.create("Render the goal panel")

    class GoalPanelApp(App[None]):
        CSS_PATH = str(
            Path(__file__).parents[1] / "src/ite/ui/reup/reup.tcss"
        )

        def compose(self) -> ComposeResult:
            yield GoalSidePanel(goal=goal.to_dict(), id="goal-panel")

    async def run() -> None:
        app = GoalPanelApp()
        async with app.run_test():
            panel = app.query_one("#goal-panel", GoalSidePanel)
            assert panel.query_one("#goal-panel-pause", Button).label == "Pause"
            assert "Render the goal panel" in panel.query_one(
                "#goal-panel-objective", Static
            ).render().plain
            for selector in (
                "#goal-panel-pause",
                "#goal-panel-edit",
                "#goal-panel-clear",
            ):
                action = panel.query_one(selector, Button)
                assert action.styles.width.value == 10
                assert action.styles.height.value == 1
                assert not action.styles.border
            goal.pause()
            panel.update_goal(goal.to_dict())
            assert panel.query_one("#goal-panel-pause", Button).label == "Resume"
            goal.resume()
            goal.metrics.work_elapsed_seconds = 187
            goal.metrics.tool_calls_succeeded = 44
            goal.metrics.tool_calls_failed = 3
            goal.metrics.verification_attempts = 1
            goal.metrics.verification_passes = 1
            goal.complete("Goal verified", evidence={"test": "passed"})
            panel.update_goal(goal.to_dict())
            assert "Completed with recorded evidence." in panel.query_one(
                "#goal-panel-detail", Static
            ).render().plain
            metrics = panel.query_one("#goal-panel-metrics", Static).render().plain
            assert "iTE worked for" not in metrics
            assert "44 tool steps completed." in metrics
            assert "3 tool steps failed; see the conversation for details." in metrics
            assert "Verification: 1 passed of 1 run." in metrics
            assert not panel.query_one("#goal-panel-pause", Button).display

    asyncio.run(run())


def test_goal_side_panel_emits_clickable_pause_request() -> None:
    goal = GoalState.create("Pause from the panel")

    class GoalPanelApp(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.pause_requested = False

        def compose(self) -> ComposeResult:
            yield GoalSidePanel(goal=goal.to_dict(), id="goal-panel")

        @on(GoalSidePanel.PauseRequested)
        def on_goal_panel_pause_requested(
            self, _event: GoalSidePanel.PauseRequested
        ) -> None:
            self.pause_requested = True

    async def run() -> None:
        app = GoalPanelApp()
        async with app.run_test() as pilot:
            await pilot.click("#goal-panel-pause")
            assert app.pause_requested

    asyncio.run(run())


def test_goal_clear_modal_does_not_block_pointer_events() -> None:
    goal = GoalState.create("Clear from the panel")

    class GoalClearModalApp(App[None]):
        CSS_PATH = str(
            Path(__file__).parents[1] / "src/ite/ui/reup/reup.tcss"
        )

        def __init__(self) -> None:
            super().__init__()
            self._goal_clear_confirmation_open = False
            self.clear_result: bool | None = None

        def compose(self) -> ComposeResult:
            yield GoalSidePanel(goal=goal.to_dict(), id="goal-panel")

        async def _open_confirmation(self) -> bool:
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self.push_screen(
                ConfirmModal(
                    title="Clear goal?",
                    body="Keeps a compact history summary.",
                    yes_label="Clear",
                    no_label="Cancel",
                    primary="no",
                ),
                callback=lambda result: future.set_result(bool(result)),
            )
            return await future

        async def _clear_goal_from_ui(self) -> None:
            if self._goal_clear_confirmation_open:
                return
            self._goal_clear_confirmation_open = True
            try:
                self.clear_result = await self._open_confirmation()
            finally:
                self._goal_clear_confirmation_open = False

        @on(GoalSidePanel.ClearRequested)
        def on_goal_panel_clear_requested(
            self, _event: GoalSidePanel.ClearRequested
        ) -> None:
            self.run_worker(self._clear_goal_from_ui(), exclusive=False)

    async def run() -> None:
        app = GoalClearModalApp()
        async with app.run_test() as pilot:
            await pilot.click("#goal-panel-clear")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.click("#no")
            await pilot.pause()
            assert app.clear_result is False

    asyncio.run(run())
