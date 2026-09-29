from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ite.agent.goal import GoalProof, GoalState, GoalStatus
from ite.agent.session import Session
from ite.agent.session_manager import SessionSnapshot
from ite.client.response import TokenUsage
from ite.tools.base import ToolInvocation
from ite.tools.builtin.goal_outcome import GoalOutcomeTool
from ite.tools.builtin.goal_progress import GoalProgressTool
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
    session.set_goal_milestones(["Implement it", "Verify it"])
    session.pause_goal()
    session.edit_goal("Implement a durable goal panel")
    archived = session.clear_goal()

    assert session.goal_state is None
    assert archived["milestones"] == []
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


def test_goal_requires_a_plan_and_proof_before_completion() -> None:
    session = _session_with_goal_fields()
    session.create_goal("Verify completion")
    outcome = GoalOutcomeTool(config=None)
    outcome.set_session(session)
    progress = GoalProgressTool(config=None)
    progress.set_session(session)

    async def run() -> tuple[object, object, object, object, object]:
        missing_proof = await outcome.execute(
            ToolInvocation(
                params={"action": "complete", "summary": "Looks finished"},
                cwd=Path("/tmp"),
            )
        )
        missing_plan = await outcome.execute(
            ToolInvocation(
                params={
                    "action": "complete",
                    "summary": "Tests passed",
                    "evidence": [
                        {
                            "kind": "command",
                            "label": "Tests passed",
                            "reference": "pytest -q",
                            "status": "passed",
                        }
                    ],
                },
                cwd=Path("/tmp"),
            )
        )
        plan = await progress.execute(
            ToolInvocation(
                params={
                    "action": "set_plan",
                    "milestones": ["Run the relevant tests"],
                },
                cwd=Path("/tmp"),
            )
        )
        milestone = session.goal_state.milestones[0]
        repeated_plan = await progress.execute(
            ToolInvocation(
                params={
                    "action": "set_plan",
                    "milestones": ["A different plan that must not replace this one"],
                },
                cwd=Path("/tmp"),
            )
        )
        await progress.execute(
            ToolInvocation(
                params={
                    "action": "complete_milestone",
                    "milestone_id": milestone.milestone_id,
                    "summary": "Relevant tests passed",
                    "evidence": [
                        {
                            "kind": "command",
                            "label": "Relevant tests passed",
                            "reference": "pytest -q",
                            "status": "passed",
                        }
                    ],
                },
                cwd=Path("/tmp"),
            )
        )
        completed = await outcome.execute(
            ToolInvocation(
                params={
                    "action": "complete",
                    "summary": "Tests passed",
                    "evidence": [
                        {
                            "kind": "command",
                            "label": "Tests passed",
                            "reference": "pytest -q",
                            "status": "passed",
                        }
                    ],
                },
                cwd=Path("/tmp"),
            )
        )
        return missing_proof, missing_plan, plan, repeated_plan, completed

    missing_proof, missing_plan, plan, repeated_plan, completed = asyncio.run(run())

    assert not missing_proof.success
    assert not missing_plan.success
    assert plan.success
    assert repeated_plan.success
    assert repeated_plan.metadata == {"action": "plan_exists", "count": 1}
    assert session.goal_state.milestones[0].milestone_id in repeated_plan.output
    assert completed.success
    assert completed.metadata == {"action": "complete"}
    assert session.goal_state.status is GoalStatus.COMPLETED
    assert session.goal_state.proofs[0].reference == "pytest -q"


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
    assert activity_title(
        "goal_progress",
        stage="complete",
        success=True,
        metadata={"action": "set_plan"},
    ) == "Goal plan recorded"
    assert describe_tool_activity(
        "goal_progress",
        {"action": "set_plan"},
        stage="complete",
        success=True,
    ) == "Recorded the goal plan."
    assert activity_title(
        "goal_progress",
        stage="complete",
        success=True,
        metadata={"action": "complete_milestone"},
    ) == "Milestone completed"
    assert describe_tool_activity(
        "goal_progress",
        {"action": "complete_milestone"},
        stage="complete",
        success=True,
    ) == "Recorded the completed milestone and its proof."


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
            goal.set_milestones(["Ship the panel", "Verify the panel"])
            for milestone in goal.milestones:
                goal.complete_milestone(
                    milestone.milestone_id,
                    summary=milestone.title,
                    evidence=[
                        GoalProof(
                            kind="command",
                            label="Goal panel tests passed",
                            reference="pytest -q tests/test_goal.py",
                            status="passed",
                        )
                    ],
                )
            goal.complete(
                "Goal verified",
                evidence=[
                    GoalProof(
                        kind="command",
                        label="Goal panel tests passed",
                        reference="pytest -q tests/test_goal.py",
                        status="passed",
                    )
                ],
            )
            panel.update_goal(goal.to_dict())
            detail = panel.query_one("#goal-panel-detail", Static).render().plain
            assert "Done — completion is supported by the proof below." in detail
            assert "✓ Ship the panel" in panel.query_one(
                "#goal-panel-plan", Static
            ).render().plain
            assert "Goal panel tests passed" in panel.query_one(
                "#goal-panel-proof", Static
            ).render().plain
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
