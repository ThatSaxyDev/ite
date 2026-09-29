from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static, TextArea

from ..change_tree import ChangedFilesTree


class CommandsSidePanel(Widget):
    ALLOW_MAXIMIZE = False

    def __init__(
        self,
        *,
        commands: list[tuple[str, str]],
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._commands = commands

    def compose(self) -> ComposeResult:
        with Horizontal(classes="commands-panel-header"):
            yield Static("Commands", classes="commands-panel-title")
            yield Button(
                "Close", id="commands-panel-close", classes="commands-panel-close"
            )
        yield Static(
            "Available slash commands and what they do.",
            classes="commands-panel-subtitle",
        )
        yield DataTable(id="commands-panel-table", classes="commands-panel-table")

    def on_mount(self) -> None:
        table = self.query_one("#commands-panel-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Command", "Description")
        for name, description in self._commands:
            table.add_row(name, description)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "commands-panel-close":
            return
        event.stop()
        self.app.run_worker(self.app._hide_commands_panel(), exclusive=False)


class HooksSidePanel(Widget):
    ALLOW_MAXIMIZE = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="hooks-panel-header"):
            yield Static("Hooks", classes="hooks-panel-title")
            yield Button("Close", id="hooks-panel-close", classes="hooks-panel-close")
        yield Static("", id="hooks-panel-summary", classes="hooks-panel-summary")
        yield VerticalScroll(id="hooks-panel-body", classes="hooks-panel-body")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "hooks-panel-close":
            return
        event.stop()
        self.app.run_worker(self.app._hide_hooks_panel(), exclusive=False)


class GoalSidePanel(Widget):
    """Right-side, click-first lifecycle surface for the current goal."""

    ALLOW_MAXIMIZE = False

    class CloseRequested(Message):
        pass

    class PauseRequested(Message):
        pass

    class ResumeRequested(Message):
        pass

    class EditRequested(Message):
        pass

    class EditSaved(Message):
        def __init__(self, objective: str) -> None:
            self.objective = objective
            super().__init__()

    class ClearRequested(Message):
        pass

    def __init__(
        self,
        *,
        goal: dict[str, object] | None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._goal = dict(goal or {})
        self._editing = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="goal-panel-header"):
            yield Static("Goal", classes="goal-panel-title")
            yield Static("", id="goal-panel-status", classes="goal-panel-status")
            yield Button("Close", id="goal-panel-close", classes="goal-panel-close")
        with ScrollableContainer(id="goal-panel-body", classes="goal-panel-body"):
            yield Static("", id="goal-panel-objective", classes="goal-panel-objective")
            yield Static("", id="goal-panel-detail", classes="goal-panel-detail")
            with Horizontal(id="goal-panel-actions", classes="goal-panel-actions"):
                yield Button("Pause", id="goal-panel-pause", variant="primary")
                yield Button("Edit", id="goal-panel-edit", variant="default")
                yield Button("Clear", id="goal-panel-clear", variant="error")
            yield Static("Plan", classes="goal-panel-section-title")
            yield Static("", id="goal-panel-plan", classes="goal-panel-plan")
            yield Static("Proof", classes="goal-panel-section-title")
            yield Static("", id="goal-panel-proof", classes="goal-panel-proof")
        with Vertical(id="goal-panel-editor", classes="goal-panel-editor"):
            yield Static("Edit goal", classes="goal-panel-section-title")
            yield TextArea(id="goal-panel-editor-input")
            with Horizontal(classes="goal-panel-actions"):
                yield Button("Save", id="goal-panel-save", variant="primary")
                yield Button("Cancel", id="goal-panel-cancel", variant="default")

    def on_mount(self) -> None:
        self._render_goal()

    def update_goal(self, goal: dict[str, object] | None) -> None:
        self._goal = dict(goal or {})
        self._render_goal()

    def begin_edit(self) -> None:
        self._editing = True
        self._render_goal()
        self.query_one("#goal-panel-editor-input", TextArea).focus()

    def finish_edit(self) -> None:
        self._editing = False
        self._render_goal()

    def _render_goal(self) -> None:
        goal = self._goal
        status = str(goal.get("status") or "paused")
        metrics = goal.get("metrics") if isinstance(goal.get("metrics"), dict) else {}
        objective = str(goal.get("objective") or "No active goal.")
        elapsed = int(float(metrics.get("active_elapsed_seconds", 0) or 0))
        minutes, seconds = divmod(elapsed, 60)
        status_label = f"{status.replace('_', ' ')} • {minutes}m {seconds:02d}s"
        self.query_one("#goal-panel-status", Static).update(status_label)
        self.query_one("#goal-panel-objective", Static).update(objective)

        milestones = (
            goal.get("milestones") if isinstance(goal.get("milestones"), list) else []
        )
        proofs = goal.get("proofs") if isinstance(goal.get("proofs"), list) else []
        detail = (
            str(goal.get("blocker"))
            if goal.get("blocker")
            else "Usage limit reached. Change provider or resume after it resets."
            if status == "budget_limited"
            else "Done — completion is supported by the proof below."
            if status == "completed"
            else "Preparing a concise plan before work begins."
            if status == "active" and not milestones
            else "Working toward the objective."
            if status == "active"
            else "Paused. Resume when you are ready."
        )
        self.query_one("#goal-panel-detail", Static).update(detail)
        plan_lines = [
            f"{'✓' if item.get('completed') else '•'} {item.get('title') or ''}"
            for item in milestones
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        self.query_one("#goal-panel-plan", Static).update(
            "\n".join(plan_lines)
            or "iTE will record the next concrete milestones before it proceeds."
        )
        proof_lines = [
            f"{'✓' if item.get('status') == 'passed' else '•'} "
            f"{item.get('label') or 'Evidence recorded'}\n"
            f"  {item.get('reference') or ''}"
            for item in proofs
            if isinstance(item, dict) and str(item.get("reference") or "").strip()
        ]
        self.query_one("#goal-panel-proof", Static).update(
            "\n".join(proof_lines)
            or "Proof will appear here as iTE verifies each milestone."
        )

        primary = self.query_one("#goal-panel-pause", Button)
        primary.label = "Pause" if status == "active" else "Resume"
        primary.display = status != "completed"
        self.query_one("#goal-panel-edit", Button).display = status != "completed"
        body = self.query_one("#goal-panel-body", ScrollableContainer)
        editor = self.query_one("#goal-panel-editor", Vertical)
        body.display = not self._editing
        editor.display = self._editing
        if self._editing:
            editor_input = self.query_one("#goal-panel-editor-input", TextArea)
            if not editor_input.text:
                editor_input.text = objective

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "goal-panel-close":
            self.post_message(self.CloseRequested())
        elif button_id == "goal-panel-pause":
            if str(self._goal.get("status")) == "active":
                self.post_message(self.PauseRequested())
            else:
                self.post_message(self.ResumeRequested())
        elif button_id == "goal-panel-edit":
            self.post_message(self.EditRequested())
        elif button_id == "goal-panel-save":
            objective = self.query_one(
                "#goal-panel-editor-input", TextArea
            ).text
            self.post_message(
                self.EditSaved(objective)
            )
        elif button_id == "goal-panel-cancel":
            self._editing = False
            self._render_goal()
        elif button_id == "goal-panel-clear":
            self.post_message(self.ClearRequested())


class ChangeReviewSidePanel(Widget):
    ALLOW_MAXIMIZE = False
    COMPACT_WIDTH = 64
    NARROW_WIDTH = 48
    _layout_mode: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="change-review-header"):
            yield Static("Changes", id="change-review-title")
            with Horizontal(id="change-review-header-actions"):
                yield Static(
                    "Stage All",
                    id="change-review-stage-all",
                    classes="change-review-action",
                )
                yield Static(
                    "Discard All",
                    id="change-review-discard-all",
                    classes="change-review-action",
                )
                yield Static(
                    "Commit",
                    id="change-review-commit",
                    classes="change-review-action",
                )
                yield Button("Close", id="change-review-close", variant="default")
        with Horizontal(id="change-review-body"):
            yield ChangedFilesTree(id="change-review-tree")
            with Vertical(id="change-review-preview-column"):
                with Horizontal(id="change-review-preview-actions"):
                    yield Static(
                        "Stage",
                        id="change-review-stage-file",
                        classes="change-review-action",
                    )
                    yield Static(
                        "Unstage",
                        id="change-review-unstage-file",
                        classes="change-review-action",
                    )
                    yield Static(
                        "Discard",
                        id="change-review-discard-file",
                        classes="change-review-action",
                    )
                yield ScrollableContainer(id="change-review-preview")

    def on_mount(self) -> None:
        self._refresh_layout_mode()

    def on_resize(self, _event: events.Resize) -> None:
        self._refresh_layout_mode()

    def _refresh_layout_mode(self) -> None:
        width = int(getattr(self.size, "width", 0) or 0)
        mode = (
            "narrow"
            if width and width < self.NARROW_WIDTH
            else "compact"
            if width and width < self.COMPACT_WIDTH
            else "wide"
        )
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        self.set_class(mode == "compact", "compact")
        self.set_class(mode == "narrow", "narrow")
        self.set_class(mode == "wide", "wide")
        labels = {
            "wide": (
                "Close",
                "Stage All",
                "Discard All",
                "Commit",
                "Stage",
                "Unstage",
                "Discard",
            ),
            "compact": (
                "Close",
                "Stage",
                "Discard",
                "Commit",
                "Stage",
                "Unstage",
                "Discard",
            ),
            "narrow": (
                "Close",
                "Stage",
                "Discard",
                "Commit",
                "Stage",
                "Unstage",
                "Discard",
            ),
        }[mode]
        (
            close_label,
            stage_all_label,
            discard_all_label,
            commit_label,
            stage_file_label,
            unstage_file_label,
            discard_file_label,
        ) = labels
        try:
            self.query_one("#change-review-close", Button).label = close_label
            self.query_one("#change-review-stage-all", Static).update(stage_all_label)
            self.query_one("#change-review-discard-all", Static).update(
                discard_all_label
            )
            self.query_one("#change-review-commit", Static).update(commit_label)
            self.query_one("#change-review-stage-file", Static).update(stage_file_label)
            self.query_one("#change-review-unstage-file", Static).update(
                unstage_file_label
            )
            self.query_one("#change-review-discard-file", Static).update(
                discard_file_label
            )
        except Exception:
            return

    def bulk_action_label(self, action: str) -> str:
        if action == "unstage":
            return "Unstage All" if self.has_class("wide") else "Unstage"
        return "Stage All" if self.has_class("wide") else "Stage"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "change-review-close":
            return
        event.stop()
        self.app.run_worker(self.app._hide_change_review_panel(), exclusive=False)
