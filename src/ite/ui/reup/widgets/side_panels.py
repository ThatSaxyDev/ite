from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual import events
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

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
