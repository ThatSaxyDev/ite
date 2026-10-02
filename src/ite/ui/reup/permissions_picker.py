"""Compact permissions picker over the active chat."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option

from ite.config.config import Config, PermissionMode
from ite.safety.permissions import DESCRIPTIONS, LABELS, current_mode


class PermissionsPickerModal(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.modes = list(PermissionMode)
        self.current = current_mode(config)

    def compose(self) -> ComposeResult:
        with Container(classes="modal permissions-modal"):
            yield Label("Permissions", classes="modal-title")
            yield Static(
                f"Current: {LABELS[self.current] if self.current else 'Custom — existing settings preserved'}",
                classes="modal-body",
            )
            with VerticalScroll(classes="permissions-content"):
                options = []
                for mode in self.modes:
                    title = Text(
                        ("✓ " if mode == self.current else "  ") + LABELS[mode],
                        style="bold",
                    )
                    options.append(
                        Option(Group(title, Text(DESCRIPTIONS[mode])), id=mode.value)
                    )
                yield OptionList(*options, id="permission-options")
            with Horizontal(classes="modal-actions"):
                yield Button("Select", id="permission-select", variant="primary")
                yield Button("Cancel", id="permission-cancel")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.highlighted = (
            self.modes.index(self.current)
            if self.current
            else self.modes.index(PermissionMode.AUTOMATIC)
        )
        options.focus()

    @on(OptionList.OptionSelected, "#permission-options")
    def selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    @on(Button.Pressed, "#permission-select")
    def select_pressed(self) -> None:
        index = self.query_one(OptionList).highlighted
        if index is not None:
            self.dismiss(self.modes[index].value)

    @on(Button.Pressed, "#permission-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)
