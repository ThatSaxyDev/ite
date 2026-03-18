from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from ite.attachments import MAX_ATTACHMENTS
from ite.config.config import Config, DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL_NAME
from ite.git.branches import BranchInfo
from rich.text import Text


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("enter", "accept", "Accept"),
        ("y", "accept", "Accept"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("1", "cancel", "Option 1"),
        ("2", "accept", "Option 2"),
    ]

    def __init__(
        self,
        title: str,
        body: str,
        yes_label: str = "Approve",
        no_label: str = "Deny",
    ) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._yes = yes_label
        self._no = no_label

    def compose(self) -> ComposeResult:
        with Container(classes="modal confirm-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._body, classes="modal-body")
            with Horizontal(classes="modal-actions"):
                yield Button(self._no, id="no", variant="default")
                yield Button(self._yes, id="yes", variant="success")

    async def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#yes")
    def on_yes_pressed(self, _event: Button.Pressed) -> None:
        self.action_accept()

    @on(Button.Pressed, "#no")
    def on_no_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()


class PlanQuestionModal(ModalScreen[dict[str, Any]]):
    def __init__(
        self,
        *,
        question_number: int,
        question: str,
        options: list[str],
        recommended_index: int | None,
        allow_free_text: bool,
    ) -> None:
        super().__init__()
        self._question_number = max(1, question_number)
        self._question = question
        self._options = options
        self._recommended_index = recommended_index
        self._allow_free_text = allow_free_text

    def compose(self) -> ComposeResult:
        with Container(classes="modal plan-modal"):
            yield Label(f"Asking questions {self._question_number}", classes="modal-title")
            yield Static(self._question, classes="modal-body")
            with Vertical(classes="modal-options"):
                for idx, option in enumerate(self._options):
                    rec = " (recommended)" if self._recommended_index == idx else ""
                    yield Button(
                        f"{idx + 1}. {option}{rec}",
                        id=f"opt-{idx}",
                        variant="primary" if self._recommended_index == idx else "default",
                    )
            if self._allow_free_text:
                yield Input(placeholder="Custom answer", id="custom-input")
                yield Button("Submit Custom", id="custom-submit", variant="warning")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("opt-"):
            idx = int(bid.split("-", 1)[1])
            option = self._options[idx]
            self.dismiss(
                {
                    "selected_option": option,
                    "free_text": "",
                    "selected_index": idx,
                }
            )
            return

        if bid == "custom-submit":
            custom_input = self.query_one("#custom-input", Input)
            value = custom_input.value.strip()
            self.dismiss(
                {
                    "selected_option": "",
                    "free_text": value,
                    "selected_index": None,
                }
            )


class SessionResumeModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        super().__init__()
        self._sessions = sessions
        self._session_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal"):
            yield Label("Resume Session", classes="modal-title resume-title")
            yield Static("Pick a session to resume.", classes="modal-body resume-body")
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="sessions", classes="resume-table", cursor_type="row")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Resume", id="resume", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if not value:
            return "-"
        text = str(value)
        try:
            return datetime.fromisoformat(text).strftime("%b %d · %I:%M %p")
        except Exception:
            return text

    async def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns("Name", "Session", "Created", "Last Used")

        self._session_ids = []
        for session in self._sessions:
            sid = str(session.get("session_id", ""))
            name = str(session.get("name") or sid)
            created = self._format_timestamp(session.get("created_at"))
            updated = self._format_timestamp(session.get("updated_at"))
            self._session_ids.append(sid)
            table.add_row(name, f"{sid[:8]}…", created, updated)
        if self._session_ids:
            table.move_cursor(row=0, column=0)
            self.query_one("#resume", Button).disabled = False

    @on(DataTable.RowHighlighted, "#sessions")
    def on_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self.query_one("#resume", Button).disabled = False

    @on(DataTable.RowSelected, "#sessions")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._session_ids):
            return
        self.dismiss(self._session_ids[event.cursor_row])

    @on(Button.Pressed, "#resume")
    def on_resume_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#sessions", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._session_ids):
            return
        self.dismiss(self._session_ids[row])

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class BranchPickerModal(ModalScreen[dict[str, str] | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, current: str, branches: list[BranchInfo]) -> None:
        super().__init__()
        self._current = current
        self._branches = branches
        self._branch_names: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal"):
            yield Label("Switch Branch", classes="modal-title resume-title")
            yield Static(
                "Pick a branch to switch, or enter a name to create one.",
                classes="modal-body resume-body",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="branches", classes="resume-table", cursor_type="row")
            yield Input(placeholder="feature/my-branch", id="branch-name")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Create", id="create", variant="success")
                yield Button("Switch", id="switch", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#branches", DataTable)
        table.add_columns("Branch", "Current")
        self._branch_names = []
        for branch in self._branches:
            self._branch_names.append(branch.name)
            table.add_row(branch.name, "✓" if branch.is_current else "")
        if self._branch_names:
            table.move_cursor(row=0, column=0)
            self.query_one("#switch", Button).disabled = False

    @on(DataTable.RowHighlighted, "#branches")
    def on_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self.query_one("#switch", Button).disabled = False

    @on(DataTable.RowSelected, "#branches")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self._branch_names):
            self.dismiss({"action": "switch", "branch": self._branch_names[event.cursor_row]})

    @on(Button.Pressed, "#switch")
    def on_switch_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#branches", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._branch_names):
            self.dismiss({"action": "switch", "branch": self._branch_names[row]})

    @on(Button.Pressed, "#create")
    def on_create_pressed(self, _event: Button.Pressed) -> None:
        value = self.query_one("#branch-name", Input).value.strip()
        self.dismiss({"action": "create", "branch": value})

    @on(Input.Submitted, "#branch-name")
    def on_branch_name_submitted(self, event: Input.Submitted) -> None:
        self.dismiss({"action": "create", "branch": event.value.strip()})

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class AttachPickerModal(ModalScreen[list[str] | None]):
    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("space", "toggle_selected", "Toggle"),
        ("enter", "toggle_selected", "Toggle"),
    ]

    def __init__(self, cwd: Path, queued_paths: list[str], files: list[Path]) -> None:
        super().__init__()
        self._cwd = cwd
        self._files = files
        self._selected_paths: set[str] = {self._path_key(Path(p)) for p in queued_paths}

    @staticmethod
    def _path_key(path: Path) -> str:
        return str(path.expanduser().absolute())

    @staticmethod
    def _discover_files(cwd: Path) -> list[Path]:
        skip_dirs = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".next",
            "dist",
            "build",
            "coverage",
            ".idea",
            ".vscode",
        }
        files: list[Path] = []
        for root, dirs, filenames in os.walk(cwd):
            dirs[:] = [
                name
                for name in dirs
                if name not in skip_dirs
                and not str(Path(root, name)).startswith(str(cwd / ".ite" / "tmp_attachments"))
            ]
            root_path = Path(root)
            for filename in filenames:
                if len(files) >= 250:
                    return files
                files.append(root_path / filename)
        return files

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal attach-modal"):
            yield Label("Attach Files", classes="modal-title resume-title")
            yield Static(
                f"Toggle files for the next message. Max {MAX_ATTACHMENTS} attachments.",
                classes="modal-body resume-body",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="attachments", classes="resume-table", cursor_type="row")
            yield Static("", id="attach-status")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Queue", id="attach-queue", variant="primary")
                yield Button("Clear", id="attach-clear", variant="default")
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#attachments", DataTable)
        table.add_columns("", "File")
        for path in self._files:
            path_key = self._path_key(path)
            marker = Text("[x]" if path_key in self._selected_paths else "[ ]")
            try:
                rel = str(path.relative_to(self._cwd))
            except Exception:
                rel = str(path)
            table.add_row(marker, rel)
        if self._files:
            table.move_cursor(row=0, column=0)
        table.focus()
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self.query_one("#attach-status", Static)
        count = len(self._selected_paths)
        tone = "#5dcf84" if count <= MAX_ATTACHMENTS else "#e35d6a"
        status.update(Text(f"Selected: {count}/{MAX_ATTACHMENTS}", style=f"bold {tone}"))

    def _toggle_current_row(self) -> None:
        table = self.query_one("#attachments", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._files):
            return
        path_key = self._path_key(self._files[row])
        if path_key in self._selected_paths:
            self._selected_paths.remove(path_key)
            marker = Text("[ ]")
        else:
            if len(self._selected_paths) >= MAX_ATTACHMENTS:
                return
            self._selected_paths.add(path_key)
            marker = Text("[x]")
        table.update_cell_at((row, 0), marker)
        self._refresh_status()

    def action_toggle_selected(self) -> None:
        self._toggle_current_row()

    @on(DataTable.RowSelected, "#attachments")
    def on_row_selected(self, _event: DataTable.RowSelected) -> None:
        self._toggle_current_row()

    @on(Button.Pressed, "#attach-queue")
    def on_queue_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(sorted(self._selected_paths))

    @on(Button.Pressed, "#attach-clear")
    def on_clear_pressed(self, _event: Button.Pressed) -> None:
        self._selected_paths.clear()
        table = self.query_one("#attachments", DataTable)
        for row in range(len(self._files)):
            table.update_cell_at((row, 0), "[ ]")
        self._refresh_status()

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class SetupModal(ModalScreen[dict[str, str] | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        with Container(classes="modal setup-modal"):
            yield Label("Setup ITE", classes="modal-title setup-title")
            yield Static(
                "Connect your provider credentials to start using reup.",
                classes="modal-body setup-body",
            )
            yield Input(
                value=self._config.base_url or DEFAULT_BASE_URL,
                placeholder=DEFAULT_BASE_URL,
                id="setup-base-url",
            )
            with Horizontal(classes="setup-secret-row"):
                yield Input(
                    value=self._config.api_key or DEFAULT_API_KEY,
                    placeholder="API key",
                    password=True,
                    id="setup-api-key",
                )
                yield Button("👁", id="setup-toggle-api-key", variant="default", classes="setup-eye")
            yield Input(
                value=self._config.model_name or DEFAULT_MODEL_NAME,
                placeholder="Model",
                id="setup-model",
            )
            yield Static("", id="setup-error", classes="setup-error")
            with Horizontal(classes="modal-actions setup-actions"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Continue", id="continue", variant="primary")

    async def on_mount(self) -> None:
        self.query_one("#setup-api-key", Input).focus()

    @on(Button.Pressed, "#continue")
    def on_continue_pressed(self, _event: Button.Pressed) -> None:
        self._submit()

    @on(Button.Pressed, "#setup-toggle-api-key")
    def on_toggle_api_key_pressed(self, event: Button.Pressed) -> None:
        api_key = self.query_one("#setup-api-key", Input)
        api_key.password = not bool(api_key.password)
        event.button.label = "🙈" if not api_key.password else "👁"

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#setup-base-url")
    @on(Input.Submitted, "#setup-api-key")
    @on(Input.Submitted, "#setup-model")
    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()

    def _set_error(self, message: str) -> None:
        self.query_one("#setup-error", Static).update(message)

    def _submit(self) -> None:
        base_url = self.query_one("#setup-base-url", Input).value.strip() or DEFAULT_BASE_URL
        api_key = self.query_one("#setup-api-key", Input).value.strip() or DEFAULT_API_KEY
        model_name = (
            self.query_one("#setup-model", Input).value.strip()
            or self._config.model_name
            or DEFAULT_MODEL_NAME
        )

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._set_error("Base URL must be a valid http/https URL.")
            return

        self.dismiss(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model_name": model_name,
                "approval": self._config.approval.value,
            }
        )
