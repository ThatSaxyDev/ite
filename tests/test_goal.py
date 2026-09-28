from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ite.agent.goal import GoalState, GoalStatus
from ite.agent.session import Session
from ite.agent.session_manager import SessionSnapshot
from ite.client.response import TokenUsage
from ite.tools.base import ToolInvocation
from ite.tools.builtin.goal_outcome import GoalOutcomeTool
from ite.ui.reup.widgets.side_panels import GoalSidePanel


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
    assert session.goal_state.status is GoalStatus.COMPLETED


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
