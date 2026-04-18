from __future__ import annotations

import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, DirectoryTree, Input, Label, Static
from textual.theme import BUILTIN_THEMES
from textual.widgets.directory_tree import DirEntry

from ite.attachments import MAX_ATTACHMENTS
from ite.client.llm_client import LLMClient
from ite.config.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_NAME,
    Config,
)
from ite.git.branches import BranchInfo, is_valid_branch_name


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
        with Container(classes="modal resume-modal confirm-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._body, classes="modal-body confirm-body")
            with Horizontal(classes="modal-actions resume-actions confirm-actions"):
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


class PushReviewModal(ModalScreen[bool]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("enter", "accept", "Accept"),
    ]

    def __init__(
        self,
        *,
        branch: str,
        target: str,
        action_label: str,
        ahead_count: int,
        behind_count: int,
        commit_subjects: list[str],
    ) -> None:
        super().__init__()
        self._branch = branch
        self._target = target
        self._action_label = action_label
        self._ahead_count = ahead_count
        self._behind_count = behind_count
        self._commit_subjects = commit_subjects

    def compose(self) -> ComposeResult:
        noun = "commit" if self._ahead_count == 1 else "commits"
        with Container(classes="modal resume-modal push-review-modal"):
            yield Label(
                "Publish branch" if self._action_label == "publish" else "Push commits",
                classes="modal-title",
            )
            with Vertical(classes="modal-body push-review-body"):
                with Horizontal(classes="push-review-row"):
                    yield Static("Branch", classes="push-review-label")
                    yield Static(self._branch, classes="push-review-value")
                with Horizontal(classes="push-review-row"):
                    yield Static("Target", classes="push-review-label")
                    yield Static(self._target, classes="push-review-value")
                with Horizontal(classes="push-review-row"):
                    yield Static("Outgoing", classes="push-review-label")
                    stats = Text()
                    stats.append(f"{self._ahead_count} {noun}", style="bold #dfe8f8")
                    stats.append("  ")
                    stats.append("↑", style="bold #79d8a4")
                    if self._behind_count > 0:
                        stats.append("    ")
                        stats.append(
                            f"{self._behind_count} behind", style="bold #f2b38f"
                        )
                    yield Static(stats, classes="push-review-value")
                if self._behind_count > 0:
                    yield Static(
                        "Remote has newer commits. Push may be rejected until you pull or rebase.",
                        classes="push-review-warning",
                    )
            with Horizontal(classes="modal-actions resume-actions push-review-actions"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button(
                    "Publish" if self._action_label == "publish" else "Push",
                    id="confirm",
                    variant="success",
                )

    async def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm")
    def on_confirm_pressed(self, _event: Button.Pressed) -> None:
        self.action_accept()

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()


class RemoteSetupModal(ModalScreen[dict[str, str] | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("enter", "submit", "Submit"),
    ]

    def __init__(
        self,
        *,
        branch: str,
        remote_name: str = "origin",
        remote_url: str = "",
    ) -> None:
        super().__init__()
        self._branch = branch
        self._remote_name = remote_name
        self._remote_url = remote_url

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal remote-setup-modal"):
            yield Label("Set up publish remote", classes="modal-title")
            with Vertical(classes="modal-body remote-setup-body"):
                with Horizontal(classes="push-review-row"):
                    yield Static("Branch", classes="push-review-label")
                    yield Static(self._branch, classes="push-review-value")
                yield Static("Remote name", classes="commit-label")
                yield Input(value=self._remote_name, id="remote-name")
                yield Static("Remote URL", classes="commit-label")
                yield Input(
                    value=self._remote_url,
                    placeholder="git@github.com:user/repo.git",
                    id="remote-url",
                )
                yield Static(
                    "Examples: git@github.com:user/repo.git  or  https://github.com/user/repo.git",
                    classes="remote-setup-help",
                )
                yield Static("", id="remote-setup-error", classes="push-review-warning")
            with Horizontal(
                classes="modal-actions resume-actions remote-setup-actions"
            ):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Save and publish", id="confirm", variant="success")

    async def on_mount(self) -> None:
        self.query_one("#remote-url", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def _set_error(self, message: str) -> None:
        self.query_one("#remote-setup-error", Static).update(message)

    @staticmethod
    def _is_valid_remote_name(value: str) -> bool:
        text = value.strip()
        return (
            bool(text)
            and not text.startswith("-")
            and not any(ch.isspace() for ch in text)
        )

    @staticmethod
    def _is_valid_remote_url(value: str) -> bool:
        text = value.strip()
        if not text or any(ch.isspace() for ch in text):
            return False
        if re.match(r"^[^@\s:]+@[^:\s]+:.+$", text) or re.match(
            r"^[^:\s]+:[^/].+$", text
        ):
            return True
        if text.startswith(("/", "./", "../", "~/")):
            return True
        parsed = urlparse(text)
        if parsed.scheme in {"http", "https", "ssh", "git", "file"}:
            return bool(parsed.netloc or parsed.path)
        return "/" in text or text.endswith(".git")

    def _submit(self) -> None:
        remote_name = self.query_one("#remote-name", Input).value.strip()
        remote_url = self.query_one("#remote-url", Input).value.strip()
        if not self._is_valid_remote_name(remote_name):
            self._set_error("Remote name cannot be empty or contain spaces.")
            return
        if not self._is_valid_remote_url(remote_url):
            self._set_error("Remote URL must be a valid git URL or path.")
            return
        self.dismiss({"remote_name": remote_name, "remote_url": remote_url})

    @on(Button.Pressed, "#confirm")
    def on_confirm_pressed(self, _event: Button.Pressed) -> None:
        self._submit()

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()

    @on(Input.Submitted, "#remote-name")
    @on(Input.Submitted, "#remote-url")
    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()


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
            yield Label(
                f"Asking questions {self._question_number}", classes="modal-title"
            )
            yield Static(self._question, classes="modal-body")
            with Vertical(classes="modal-options"):
                for idx, option in enumerate(self._options):
                    rec = " (recommended)" if self._recommended_index == idx else ""
                    yield Button(
                        f"{idx + 1}. {option}{rec}",
                        id=f"opt-{idx}",
                        variant="primary"
                        if self._recommended_index == idx
                        else "default",
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


class CommitModal(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]
    _AI_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    _AI_LOADING_LINES = (
        "Reading diff",
        "Finding scope",
        "Shaping subject",
        "Cutting noise",
        "Tracing intent",
        "Naming change",
        "Polishing line",
        "Weighing impact",
        "Checking files",
        "Finding signal",
        "Sizing change",
        "Scanning hunks",
        "Tracking edits",
        "Mapping scope",
        "Reading context",
        "Blending intent",
        "Scoring options",
        "Cleaning verbs",
        "Tightening scope",
        "Balancing tone",
        "Filtering noise",
        "Drafting subject",
        "Trimming words",
        "Checking punch",
        "Refining line",
        "Testing fit",
        "Finding shape",
        "Choosing angle",
        "Sorting clues",
        "Pinning impact",
    )
    _AI_STATUS_DELAYS = (0.8, 1.1, 1.4, 1.8, 2.2, 2.8, 3.4)

    def __init__(
        self,
        *,
        config: Config,
        llm_client: LLMClient | None = None,
        branch: str,
        file_count: int,
        additions: int,
        deletions: int,
        changed_paths: list[str],
        diff_context: str,
        push_label: str = "Commit and push",
    ) -> None:
        super().__init__()
        self._config = config
        self._llm_client = llm_client
        self._branch = branch
        self._file_count = file_count
        self._additions = additions
        self._deletions = deletions
        self._changed_paths = changed_paths
        self._diff_context = diff_context
        self._push_label = push_label
        self._include_unstaged = True
        self._generating_commit_message = False
        self._ai_spinner_index = 0
        self._ai_spinner_timer = None
        self._ai_copy_timer = None
        self._last_ai_error: str | None = None
        self._ai_loading_step = 0
        self._rng = random.Random(
            "|".join(self._changed_paths) or f"{self._branch}:{self._file_count}"
        )
        self._ai_loading_seed = (
            sum(ord(char) for char in " ".join(self._changed_paths))
            % len(self._AI_LOADING_LINES)
            if self._changed_paths
            else 0
        )

    def _include_unstaged_text(self) -> Text:
        text = Text()
        if self._include_unstaged:
            text.append("YES", style="bold #79d8a4")
            text.append("  ")
            text.append("no", style="#8c93a1")
        else:
            text.append("yes", style="#8c93a1")
            text.append("  ")
            text.append("NO", style="bold #f29b9b")
        return text

    def _suggest_commit_message(self) -> str:
        paths = [path for path in self._changed_paths if path]
        if not paths:
            return "chore: update working tree"

        joined = " ".join(paths).lower()
        if "reup" in joined and "commit" in joined:
            return "feat(ui): refine commit modal flow"
        if "reup" in joined and any(
            token in joined for token in {"modal", "modals", "tcss"}
        ):
            return "style(ui): polish modal layout and spacing"
        if "working_tree" in joined and "reup" in joined:
            return "feat(ui): improve working tree review actions"
        if "working_tree" in joined or "changes" in joined:
            return "feat(git): improve working tree change review"
        if "app.py" in joined and "modals.py" in joined:
            return "refactor(ui): tighten modal interactions"

        if len(paths) == 1:
            stem = Path(paths[0]).stem
            words = re.sub(r"[_-]+", " ", stem).strip()
            parent = Path(paths[0]).parent.name
            scope = parent if parent and parent not in {"src", "ite"} else stem
            return f"chore({scope}): update {words}"

        common_prefix = os.path.commonpath(paths)
        common_parts = [
            part
            for part in common_prefix.split(os.sep)
            if part and part not in {"src", "ite", "ui", "docs"}
        ]
        if common_parts:
            topic = " ".join(common_parts[-2:])
            scope = common_parts[-1]
            return f"refactor({scope}): refine {topic}"

        top_level = {path.split("/", 1)[0] for path in paths if "/" in path}
        if len(top_level) == 1:
            scope = next(iter(top_level))
            return f"chore({scope}): update related files"

        return "chore: update related files"

    async def _generate_commit_message(self) -> str:
        client = self._llm_client or LLMClient(self._config)
        owns_client = self._llm_client is None
        self._last_ai_error = None
        attempts = (
            self._build_commit_messages(mode="rich"),
            self._build_commit_messages(mode="simple"),
            self._build_commit_messages(mode="minimal"),
        )
        try:
            for messages in attempts:
                try:
                    content = await client.complete_text(messages)
                    if not content.strip():
                        raise ValueError(
                            "Commit subject generation returned an empty response."
                        )
                    return self._normalize_commit_message(content)
                except ValueError as exc:
                    self._last_ai_error = str(exc)
                    continue
                except RuntimeError as exc:
                    self._last_ai_error = (
                        str(exc) or "Commit subject generation failed."
                    )
                    continue
        finally:
            if owns_client:
                await client.close()
        return self._suggest_commit_message()

    def _build_commit_messages(self, *, mode: str) -> list[dict[str, str]]:
        system = (
            "You write excellent git commit subjects. "
            "Return exactly one concise subject line, max 72 characters. "
            "Prefer conventional commit style like feat(scope):, fix(scope):, refactor(scope):, "
            "style(scope):, chore(scope): when it fits naturally. "
            "Summarize the intent and user-visible effect of the change, not the filenames. "
            "Use an imperative verb. Avoid vague messages like 'update files' or 'misc fixes'. "
            "Do not use quotes, bullets, code fences, or any explanation."
        )
        if mode == "minimal":
            user = (
                "Write one git commit subject.\n\n"
                f"Branch: {self._branch}\n"
                "Paths: " + ", ".join(self._changed_paths[:6]) + "\n"
                f"Stats: +{self._additions} -{self._deletions}"
            )
        elif mode == "simple":
            user = (
                "Write one git commit subject for these changes.\n\n"
                f"Branch: {self._branch}\n"
                f"Stats: {self._file_count} files, +{self._additions}, -{self._deletions}\n"
                "Paths: " + ", ".join(self._changed_paths[:8]) + "\n"
                f"Summary: {self._diff_context[:900]}"
            )
        else:
            user = (
                "Based on this git information, write the best commit subject.\n\n"
                f"Branch: {self._branch}\n"
                f"Files changed: {self._file_count}\n"
                f"Additions: {self._additions}\n"
                f"Deletions: {self._deletions}\n"
                "Changed paths:\n- " + "\n- ".join(self._changed_paths[:12]) + "\n\n"
                "Focused change summary:\n"
                f"{self._diff_context}"
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _normalize_commit_message(content: str) -> str:
        line = content.strip().splitlines()[0].strip()
        line = line.strip("\"'` ")
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"^(commit message:|subject:)\s*", "", line, flags=re.IGNORECASE)
        return line[:72].rstrip() or "chore: update related files"

    def _loading_copy(self, step: int) -> str:
        index = (self._ai_loading_seed + max(0, step)) % len(self._AI_LOADING_LINES)
        return self._AI_LOADING_LINES[index]

    def _loading_status_text(self) -> Text:
        frame = self._AI_SPINNER_FRAMES[
            self._ai_spinner_index % len(self._AI_SPINNER_FRAMES)
        ]
        message = self._loading_copy(self._ai_loading_step)
        status = Text()
        status.append(f"{frame} ", style="bold #8fb7dc")
        status.append(message, style="italic #aeb7c6")
        return status

    @staticmethod
    def _idle_status_text() -> Text:
        status = Text()
        status.append("✦ ", style="bold #8fb7dc")
        status.append("draft with AI", style="#8c93a1")
        return status

    @staticmethod
    def _success_status_text() -> Text:
        status = Text()
        status.append("✓ ", style="bold #79d8a4")
        status.append("draft ready", style="#9fb4a8")
        return status

    def _set_ai_status_idle(self) -> None:
        self.query_one("#commit-ai-status", Static).update(self._idle_status_text())

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal commit-modal"):
            yield Label("Commit your changes", classes="modal-title")
            with Vertical(classes="modal-body commit-body"):
                with Horizontal(classes="commit-summary-row"):
                    yield Static("Branch", classes="commit-label")
                    yield Static(self._branch, classes="commit-branch")
                with Horizontal(classes="commit-summary-row"):
                    yield Static("Changes", classes="commit-label")
                    stats = Text()
                    file_label = (
                        f"{self._file_count} file"
                        if self._file_count == 1
                        else f"{self._file_count} files"
                    )
                    stats.append(file_label, style="bold #dfe8f8")
                    stats.append("  ")
                    stats.append(f"+{self._additions}", style="bold #79d8a4")
                    stats.append("  ")
                    stats.append(f"-{self._deletions}", style="bold #f29b9b")
                    yield Static(stats, classes="commit-stats")
                with Horizontal(classes="commit-toggle-row"):
                    yield Static("Include unstaged", classes="commit-label")
                    yield Static(
                        self._include_unstaged_text(),
                        id="commit-include-unstaged-choice",
                        classes="commit-toggle-choice",
                    )
                with Horizontal(classes="commit-message-header"):
                    yield Static(
                        "Commit message", classes="commit-label commit-message-label"
                    )
                    yield Static(
                        self._idle_status_text(),
                        id="commit-ai-status",
                        classes="commit-ai-status",
                    )
                with Horizontal(classes="commit-message-row"):
                    yield Input(
                        placeholder="Type a commit message or use ✦ to generate one",
                        id="commit-message",
                    )
                    yield Button("✦", id="commit-ai-fill", variant="default")
            with Horizontal(classes="modal-actions resume-actions commit-actions"):
                yield Button(
                    "Commit", id="commit-confirm", variant="primary", disabled=True
                )
                yield Button(
                    self._push_label, id="commit-push", variant="success", disabled=True
                )
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        self.query_one("#commit-message", Input).focus()
        self._update_commit_actions()
        self._set_ai_status_idle()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _dismiss_with_action(self, action: str) -> None:
        message = self.query_one("#commit-message", Input).value.strip()
        if not message:
            self.query_one("#commit-message", Input).focus()
            return
        self.dismiss(
            {
                "action": action,
                "message": message,
                "include_unstaged": self._include_unstaged,
            }
        )

    def _update_commit_actions(self) -> None:
        has_message = bool(self.query_one("#commit-message", Input).value.strip())
        self.query_one("#commit-confirm", Button).disabled = not has_message
        self.query_one("#commit-push", Button).disabled = not has_message

    @on(events.Click, "#commit-include-unstaged-choice")
    def on_include_unstaged_choice_clicked(self, _event: events.Click) -> None:
        self._include_unstaged = not self._include_unstaged
        self.query_one("#commit-include-unstaged-choice", Static).update(
            self._include_unstaged_text()
        )

    @on(Input.Changed, "#commit-message")
    def on_commit_message_changed(self, _event: Input.Changed) -> None:
        self._update_commit_actions()

    @on(Button.Pressed, "#commit-ai-fill")
    def on_commit_ai_fill_pressed(self, _event: Button.Pressed) -> None:
        if self._generating_commit_message:
            return
        self.run_worker(self._fill_commit_message_from_ai(), exclusive=False)

    def _tick_ai_spinner(self) -> None:
        if not self._generating_commit_message:
            return
        button = self.query_one("#commit-ai-fill", Button)
        status_widget = self.query_one("#commit-ai-status", Static)
        button.label = self._AI_SPINNER_FRAMES[
            self._ai_spinner_index % len(self._AI_SPINNER_FRAMES)
        ]
        status_widget.update(self._loading_status_text())
        self._ai_spinner_index += 1

    def _tick_ai_copy(self) -> None:
        if not self._generating_commit_message:
            return
        self._ai_loading_step += 1
        self.query_one("#commit-ai-status", Static).update(self._loading_status_text())
        self._schedule_ai_status_tick()

    def _schedule_ai_status_tick(self) -> None:
        if not self._generating_commit_message:
            return
        delay = self._rng.choice(self._AI_STATUS_DELAYS)
        self._ai_copy_timer = self.set_timer(delay, self._tick_ai_copy)

    async def _fill_commit_message_from_ai(self) -> None:
        self._generating_commit_message = True
        button = self.query_one("#commit-ai-fill", Button)
        input_widget = self.query_one("#commit-message", Input)
        status_widget = self.query_one("#commit-ai-status", Static)
        original_label = button.label
        self._ai_spinner_index = 0
        self._ai_loading_step = 0
        self._last_ai_error = None
        status_widget.update(self._loading_status_text())
        button.label = self._AI_SPINNER_FRAMES[0]
        button.disabled = True
        self._ai_spinner_timer = self.set_interval(0.12, self._tick_ai_spinner)
        self._schedule_ai_status_tick()
        try:
            input_widget.value = await self._generate_commit_message()
            if self._last_ai_error:
                self._set_ai_status_idle()
            else:
                status_widget.update(self._success_status_text())
            input_widget.focus()
        finally:
            if self._ai_spinner_timer is not None:
                self._ai_spinner_timer.stop()
                self._ai_spinner_timer = None
            if self._ai_copy_timer is not None:
                self._ai_copy_timer.stop()
                self._ai_copy_timer = None
            button.label = original_label
            button.disabled = False
            self._generating_commit_message = False

    @on(Button.Pressed, "#commit-confirm")
    def on_commit_confirm_pressed(self, _event: Button.Pressed) -> None:
        self._dismiss_with_action("commit")

    @on(Button.Pressed, "#commit-push")
    def on_commit_push_pressed(self, _event: Button.Pressed) -> None:
        self._dismiss_with_action("commit_push")

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()


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
                yield DataTable(
                    id="sessions", classes="resume-table", cursor_type="row"
                )
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
                yield DataTable(
                    id="branches", classes="resume-table", cursor_type="row"
                )
            yield Input(placeholder="feature/my-branch", id="branch-name")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Create", id="create", variant="success", disabled=True)
                yield Button("Switch", id="switch", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    def _update_create_state(self) -> None:
        value = self.query_one("#branch-name", Input).value.strip()
        self.query_one("#create", Button).disabled = not is_valid_branch_name(value)

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
            self.dismiss(
                {"action": "switch", "branch": self._branch_names[event.cursor_row]}
            )

    @on(Button.Pressed, "#switch")
    def on_switch_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#branches", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._branch_names):
            self.dismiss({"action": "switch", "branch": self._branch_names[row]})

    @on(Button.Pressed, "#create")
    def on_create_pressed(self, _event: Button.Pressed) -> None:
        value = self.query_one("#branch-name", Input).value.strip()
        if not is_valid_branch_name(value):
            self.query_one("#branch-name", Input).focus()
            return
        self.dismiss({"action": "create", "branch": value})

    @on(Input.Changed, "#branch-name")
    def on_branch_name_changed(self, _event: Input.Changed) -> None:
        self._update_create_state()

    @on(Input.Submitted, "#branch-name")
    def on_branch_name_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not is_valid_branch_name(value):
            self.query_one("#branch-name", Input).focus()
            return
        self.dismiss({"action": "create", "branch": value})

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ModelPickerModal(ModalScreen[dict[str, str] | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, current: str, models: list[dict[str, Any]]) -> None:
        super().__init__()
        self._current = current
        self._models = models
        self._model_names: list[str] = []
        self._model_available: list[bool] = []
        self._model_unavailable_reasons: list[str] = []
        self._model_sources: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal"):
            yield Label("Select model", classes="modal-title resume-title")
            yield Static(
                "Pick an available bundled model, or keep your current custom provider model.",
                classes="modal-body resume-body",
                id="model-picker-help",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="models", classes="resume-table", cursor_type="row")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Delete saved", id="delete", variant="default", disabled=True)
                yield Button("Select", id="select", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#models", DataTable)
        table.add_columns("Model", "Source", "Status", "Current")
        self._model_names = []
        self._model_available = []
        self._model_unavailable_reasons = []
        self._model_sources = []
        for item in self._models:
            model_name = str(item.get("model_name") or "").strip()
            label = str(item.get("label") or model_name).strip()
            provider = str(item.get("provider") or "").strip()
            available = bool(item.get("available", True))
            unavailable_reason = str(item.get("unavailable_reason") or "").strip()
            if not model_name:
                continue
            self._model_names.append(model_name)
            self._model_available.append(available)
            self._model_unavailable_reasons.append(unavailable_reason)
            self._model_sources.append(provider)
            table.add_row(
                label,
                provider,
                "Available" if available else "Unavailable",
                "✓" if model_name == self._current else "",
            )
        if self._model_names:
            initial_row = (
                self._model_names.index(self._current)
                if self._current in self._model_names
                else 0
            )
            table.move_cursor(row=initial_row, column=0)
            self._refresh_selection_state(initial_row)

    def _refresh_selection_state(self, row: int) -> None:
        select_button = self.query_one("#select", Button)
        delete_button = self.query_one("#delete", Button)
        help_text = self.query_one("#model-picker-help", Static)
        if not (0 <= row < len(self._model_names)):
            select_button.disabled = True
            delete_button.disabled = True
            help_text.update(
                "Pick an available model, or delete a saved custom profile."
            )
            return

        available = self._model_available[row]
        source = self._model_sources[row]
        select_button.disabled = not available
        delete_button.disabled = source != "Saved custom"
        if available:
            help_text.update(
                "Pick an available model, or delete a saved custom profile."
            )
            return

        reason = self._model_unavailable_reasons[row]
        if reason:
            help_text.update(f"This model is unavailable right now. {reason}")
        else:
            help_text.update("This model is unavailable right now.")

    @on(DataTable.RowHighlighted, "#models")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._refresh_selection_state(event.cursor_row)

    @on(DataTable.RowSelected, "#models")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self._model_names) and self._model_available[event.cursor_row]:
            self.dismiss({"action": "select", "model_name": self._model_names[event.cursor_row]})

    @on(Button.Pressed, "#select")
    def on_select_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#models", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._model_names) and self._model_available[row]:
            self.dismiss({"action": "select", "model_name": self._model_names[row]})

    @on(Button.Pressed, "#delete")
    def on_delete_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#models", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._model_names) and self._model_sources[row] == "Saved custom":
            self.dismiss({"action": "delete", "model_name": self._model_names[row]})

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ThemePickerModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current
        self._theme_names = sorted(BUILTIN_THEMES.keys())

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal theme-picker-modal"):
            yield Label("Select theme", classes="modal-title resume-title")
            yield Static(
                "Choose a Textual theme for the current session.",
                classes="modal-body resume-body",
                id="theme-picker-help",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="themes", classes="resume-table", cursor_type="row")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Select", id="select", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#themes", DataTable)
        table.add_columns("Theme", "Mode", "Current")
        initial_row = 0
        for index, name in enumerate(self._theme_names):
            theme = BUILTIN_THEMES[name]
            table.add_row(name, "Dark" if theme.dark else "Light", "✓" if name == self._current else "")
            if name == self._current:
                initial_row = index
        if self._theme_names:
            table.move_cursor(row=initial_row, column=0)

    @on(DataTable.RowSelected, "#themes")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self._theme_names):
            self.dismiss(self._theme_names[event.cursor_row])

    @on(Button.Pressed, "#select")
    def on_select_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#themes", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._theme_names):
            self.dismiss(self._theme_names[row])

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class UsageSummaryModal(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, summary: dict[str, Any]) -> None:
        super().__init__()
        self._summary = summary

    def _format_reset(self, value: str, label: str) -> str:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return "Resets soon"
        if label == "5h":
            return f"Resets {dt.strftime('%-I:%M%p').lower()}"
        return f"Resets {dt.strftime('%B %-d at %-I:%M%p').lower()}"

    @staticmethod
    def _build_bar(remaining_percent: int, width: int = 92) -> Text:
        used_percent = max(0, min(100, 100 - remaining_percent))
        filled = max(0, min(width, round((used_percent / 100) * width)))
        empty = max(0, width - filled)
        bar = Text()
        if filled:
            bar.append("━" * filled, style="bold #f3f4f6")
        if empty:
            bar.append("━" * empty, style="#34363a")
        return bar

    def _build_renderable(self) -> Group:
        quotas = self._summary.get("quotas") or {}
        sections: list[object] = []
        for label, key in (("5h", "fiveHour"), ("Weekly", "sevenDay")):
            quota = quotas.get(key) or {}
            used = int(quota.get("usedUsdCents") or 0)
            cap = max(1, int(quota.get("capUsdCents") or 1))
            remaining = max(0, min(100, round(((cap - used) / cap) * 100)))

            row = Table.grid(expand=True)
            row.add_column(ratio=1)
            row.add_column(justify="right", width=18)
            row.add_row(
                Text(label, style="bold #f3f4f6"),
                Text(f"{remaining}% remaining", style="bold #f3f4f6"),
            )
            sections.append(row)
            sections.append(
                Text(
                    self._format_reset(str(quota.get("nextResetAt") or ""), label),
                    style="#8f949d",
                )
            )
            sections.append(self._build_bar(remaining))
            if key != "sevenDay":
                sections.append(Text(""))
        return Group(*sections)

    def compose(self) -> ComposeResult:
        with Container(classes="modal usage-modal"):
            yield Label("Usage", classes="modal-title")
            with Container(classes="usage-summary-panel"):
                yield Static(self._build_renderable(), classes="usage-summary-body")
            with Horizontal(classes="modal-actions"):
                yield Button("Close", id="cancel", variant="default")

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ContextSummaryModal(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__()
        self._payload = payload

    @staticmethod
    def _build_bar(used_percent: float, width: int = 92) -> Text:
        normalized = max(0, min(100, round(used_percent)))
        filled = max(0, min(width, round((normalized / 100) * width)))
        empty = max(0, width - filled)
        bar = Text()
        if filled:
            bar.append("━" * filled, style="bold #f3f4f6")
        if empty:
            bar.append("━" * empty, style="#34363a")
        return bar

    @staticmethod
    def _format_compacted_at(value: str | None) -> str:
        if not value:
            return "No compactions yet"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return value
        return dt.strftime("%b %-d, %-I:%M%p").lower()

    def _build_renderable(self) -> Group:
        context_window = int(self._payload.get("context_window") or 0)
        latest_tokens = int(self._payload.get("latest_tokens") or 0)
        used_pct = float(self._payload.get("context_used_pct") or 0.0)
        trigger_at = int(self._payload.get("trigger_at") or 0)
        trigger_pct = (trigger_at / context_window * 100) if context_window else 0.0

        summary = Table.grid(expand=True)
        summary.add_column(ratio=1)
        summary.add_column(justify="right", width=22)
        summary.add_row(
            Text("Current context", style="bold #f3f4f6"),
            Text(f"{latest_tokens}/{context_window} tokens", style="bold #f3f4f6"),
        )
        summary.add_row(
            Text(
                f"{used_pct:.1f}% used",
                style="bold #d1d5db",
            ),
            Text(
                f"Auto-compact at {trigger_pct:.1f}%",
                style="#8f949d",
            ),
        )
        return Group(summary, self._build_bar(used_pct))

    def compose(self) -> ComposeResult:
        with Container(classes="modal context-modal"):
            yield Label("Context window", classes="modal-title")
            yield Static(
                "iTE automatically manages your context window.",
                classes="modal-body",
            )
            with Container(classes="usage-summary-panel"):
                yield Static(self._build_renderable(), classes="usage-summary-body")
            with Horizontal(classes="modal-actions"):
                yield Button("Close", id="cancel", variant="default")

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ActivityModal(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__()
        self._payload = payload
        self._events = (
            payload.get("events") if isinstance(payload.get("events"), list) else []
        )
        self._analytics = (
            payload.get("analytics")
            if isinstance(payload.get("analytics"), dict)
            else {}
        )

    @staticmethod
    def _format_when(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return value
        return dt.strftime("%b %-d, %-I:%M%p").lower()

    @staticmethod
    def _title_for(event_type: str) -> str:
        mapping = {
            "billing.checkout_started": "Started checkout",
            "billing.subscription_updated": "Subscription updated",
            "billing.subscription_synced": "Billing synced",
            "billing.portal_opened": "Opened billing portal",
            "billing.plan_downgraded": "Moved to Free",
            "auth.cli_approved": "Approved terminal sign-in",
            "session.terminal_created": "Created terminal session",
            "session.terminal_signed_out": "Signed out terminal session",
            "session.revoked": "Revoked device session",
            "auth.terminal_refreshed": "Refreshed terminal session",
            "usage.request_succeeded": "Used bundled model",
            "usage.request_blocked_quota": "Bundled usage blocked",
            "usage.request_failed": "Bundled request failed",
            "usage.request_unavailable": "Bundled model unavailable",
        }
        return mapping.get(event_type, event_type.replace(".", " "))

    @staticmethod
    def _detail_for(event: dict[str, Any]) -> str:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        model = metadata.get("model")
        window = metadata.get("window")
        plan_key = metadata.get("planKey")
        status = metadata.get("status")
        source = str(event.get("source") or "").replace(".", " ")
        if isinstance(model, str) and isinstance(window, str):
            return f"{model} · {window}"
        if isinstance(model, str):
            return model
        if isinstance(plan_key, str) and isinstance(status, str):
            return f"{plan_key} · {status}"
        if isinstance(plan_key, str):
            return plan_key
        return source

    @staticmethod
    def _format_usd(cents: int) -> str:
        return f"${(cents / 100):.2f}"

    @staticmethod
    def _format_ngn(cents: int) -> str:
        amount = (cents / 100) * 1397.98
        return f"₦{amount:,.0f}"

    @staticmethod
    def _format_period(start: str | None, end: str | None) -> str:
        if not start or not end:
            return "Current billing period"
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone()
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return "Current billing period"
        return f"{start_dt.strftime('%b %-d')} to {end_dt.strftime('%b %-d')}".lower()

    def _build_summary(self) -> Group:
        totals = self._analytics.get("totals")
        if not isinstance(totals, dict):
            return Group(Text("No bundled usage yet.", style="#8f949d"))

        current_period = self._analytics.get("currentPeriod")
        if not isinstance(current_period, dict):
            current_period = {"start": None, "end": None}

        top = Table.grid(expand=True)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_row(
            Text("Today", style="#8f949d"),
            Text("7 days", style="#8f949d"),
            Text("Billing period", style="#8f949d"),
            Text("All time", style="#8f949d"),
        )
        top.add_row(
            Text(
                self._format_usd(int(totals.get("todayUsdCents") or 0)),
                style="bold #f3f4f6",
            ),
            Text(
                self._format_usd(int(totals.get("sevenDayUsdCents") or 0)),
                style="bold #f3f4f6",
            ),
            Text(
                self._format_usd(int(totals.get("currentPeriodUsdCents") or 0)),
                style="bold #f3f4f6",
            ),
            Text(
                self._format_usd(int(totals.get("allTimeUsdCents") or 0)),
                style="bold #f3f4f6",
            ),
        )
        top.add_row(
            Text(
                self._format_ngn(int(totals.get("todayUsdCents") or 0)), style="#8f949d"
            ),
            Text(
                self._format_ngn(int(totals.get("sevenDayUsdCents") or 0)),
                style="#8f949d",
            ),
            Text(
                self._format_period(
                    current_period.get("start")
                    if isinstance(current_period.get("start"), str)
                    else None,
                    current_period.get("end")
                    if isinstance(current_period.get("end"), str)
                    else None,
                ),
                style="#8f949d",
            ),
            Text(
                f"{self._format_ngn(int(totals.get('allTimeUsdCents') or 0))}  ·  {int(totals.get('allTimeRequestCount') or 0)} requests",
                style="#8f949d",
            ),
        )

        by_model = self._analytics.get("byModel")
        model_table = Table.grid(expand=True)
        model_table.add_column(ratio=1)
        model_table.add_column(justify="right", width=14)
        model_table.add_column(justify="right", width=16)
        if isinstance(by_model, list) and by_model:
            model_table.add_row(
                Text("Model", style="#8f949d"),
                Text("Spend", style="#8f949d"),
                Text("Share", style="#8f949d"),
            )
            for row in by_model[:3]:
                if not isinstance(row, dict):
                    continue
                model_table.add_row(
                    Text(
                        self._model_label(str(row.get("modelKey") or "")),
                        style="#f3f4f6",
                    ),
                    Text(
                        self._format_usd(int(row.get("usdCents") or 0)), style="#f3f4f6"
                    ),
                    Text(
                        f"{self._format_ngn(int(row.get('usdCents') or 0))}  ·  {int(row.get('sharePercent') or 0)}%",
                        style="#8f949d",
                    ),
                )
        else:
            model_table.add_row(
                Text("No model spend yet.", style="#8f949d"), Text(""), Text("")
            )

        return Group(
            top,
            Rule(style="#2a2d31"),
            Text("Top models", style="bold #f3f4f6"),
            model_table,
        )

    @staticmethod
    def _model_label(model_key: str) -> str:
        mapping = {
            "kimi-k2.5": "Kimi K2.5",
            "minimax-m2.7": "MiniMax M2.7",
            "glm-5": "GLM-5",
            "glm-5.1": "GLM-5.1",
        }
        return mapping.get(model_key, model_key)

    def _build_table(self) -> DataTable:
        table = DataTable(cursor_type="row")
        table.add_columns("Activity", "Details", "When")
        for event in self._events[:50]:
            table.add_row(
                self._title_for(str(event.get("eventType") or "")),
                self._detail_for(event),
                self._format_when(str(event.get("createdAt") or "")),
            )
        return table

    def compose(self) -> ComposeResult:
        with Container(classes="modal activity-modal"):
            yield Label("Usage analytics", classes="modal-title")
            yield Static(
                "Bundled spend and model mix across your account.", classes="modal-body"
            )
            with Container(classes="usage-summary-panel"):
                yield Static(self._build_summary(), classes="usage-summary-body")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Close", id="cancel", variant="default")

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class AttachPickerModal(ModalScreen[list[str] | None]):
    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("space", "toggle_selected", "Toggle"),
        ("ctrl+u", "go_parent", "Parent"),
        ("ctrl+h", "go_home", "Home"),
        ("ctrl+r", "refresh_tree", "Refresh"),
    ]

    class AttachDirectoryTree(DirectoryTree):
        async def set_root_path(self, path: Path) -> None:
            resolved = path.expanduser().resolve()
            self.path = str(resolved)
            self.reset_node(self.root, str(resolved), DirEntry(self.PATH(resolved)))
            await self.reload()
            self.cursor_line = 0
            self.scroll_to(0, 0, animate=False)

    def __init__(self, cwd: Path, queued_paths: list[str]) -> None:
        super().__init__()
        self._cwd = cwd.resolve()
        self._root = self._cwd
        self._selected_paths: set[str] = {self._path_key(Path(p)) for p in queued_paths}
        self._highlighted_path: str = ""

    @staticmethod
    def _path_key(path: Path) -> str:
        return str(path.expanduser().absolute())

    @staticmethod
    def _resolve_root_path(
        raw: str, *, cwd: Path, current_root: Path | None = None
    ) -> Path:
        candidate = (raw or "").strip()
        base = current_root.resolve() if current_root is not None else cwd.resolve()
        if not candidate:
            return base
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = (base / path).resolve()
        else:
            path = path.resolve()
        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Not a directory: {path}")
        return path

    def _selection_summary(self) -> str:
        count = len(self._selected_paths)
        if count == 0:
            return "No files selected."
        names = [Path(path).name for path in sorted(self._selected_paths)]
        preview = ", ".join(names[:3])
        if count > 3:
            preview += f" (+{count - 3} more)"
        return preview

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal attach-modal"):
            yield Label("Attach Files", classes="modal-title resume-title")
            yield Static(
                f"Browse and queue files for the next message. Max {MAX_ATTACHMENTS} attachments.",
                classes="modal-body resume-body",
            )
            with Horizontal(classes="attach-root-row"):
                yield Button("Home", id="attach-home", variant="default")
                yield Button("Up", id="attach-up", variant="default")
                yield Input(value=str(self._cwd), id="attach-root")
                yield Button("Go", id="attach-go", variant="primary")
            with Container(classes="modal-list resume-list"):
                yield self.AttachDirectoryTree(str(self._cwd), id="attachment-tree")
            yield Static("", id="attach-preview")
            yield Static("", id="attach-status")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Queue", id="attach-queue", variant="primary")
                yield Button("Clear", id="attach-clear", variant="default")
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        tree = self.query_one("#attachment-tree", self.AttachDirectoryTree)
        await tree.reload()
        tree.focus()
        self._refresh_status()
        self._refresh_preview()

    def _refresh_status(self) -> None:
        status = self.query_one("#attach-status", Static)
        count = len(self._selected_paths)
        tone = "#4edea3" if count <= MAX_ATTACHMENTS else "#ffb95f"
        summary = self._selection_summary()
        status.update(
            Text(
                f"Selected: {count}/{MAX_ATTACHMENTS}  •  {summary}",
                style=f"bold {tone}",
            )
        )

    def _refresh_preview(self) -> None:
        preview = self.query_one("#attach-preview", Static)
        if not self._highlighted_path:
            preview.update(
                Text("Navigate the tree, press space to select files.", style="#8c97ab")
            )
            return
        path = Path(self._highlighted_path)
        kind = "directory" if path.is_dir() else "file"
        selected = self._path_key(path) in self._selected_paths
        status = "selected" if selected else "not selected"
        preview.update(Text(f"{path}  •  {kind}  •  {status}", style="#8c97ab"))

    def _current_tree_path(self) -> Path | None:
        tree = self.query_one("#attachment-tree", self.AttachDirectoryTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return None
        entry = node.data
        try:
            return Path(entry.path).resolve()
        except Exception:
            return None

    def _toggle_current_selection(self) -> None:
        path = self._current_tree_path()
        if path is None or not path.is_file():
            return
        path_key = self._path_key(path)
        if path_key in self._selected_paths:
            self._selected_paths.remove(path_key)
        else:
            if len(self._selected_paths) >= MAX_ATTACHMENTS:
                return
            self._selected_paths.add(path_key)
        self._refresh_status()
        self._refresh_preview()

    def action_toggle_selected(self) -> None:
        self._toggle_current_selection()

    async def _set_root_path(self, root: Path) -> None:
        resolved = root.expanduser().resolve()
        self._root = resolved
        self.query_one("#attach-root", Input).value = str(resolved)
        tree = self.query_one("#attachment-tree", self.AttachDirectoryTree)
        await tree.set_root_path(resolved)
        self._highlighted_path = str(resolved)
        self._refresh_preview()

    async def action_go_parent(self) -> None:
        parent = self._root.parent
        if parent == self._root:
            return
        await self._set_root_path(parent)

    async def action_go_home(self) -> None:
        await self._set_root_path(Path.home())

    async def action_refresh_tree(self) -> None:
        tree = self.query_one("#attachment-tree", self.AttachDirectoryTree)
        await tree.reload()

    @on(DirectoryTree.NodeHighlighted, "#attachment-tree")
    def on_tree_highlighted(self, event: DirectoryTree.NodeHighlighted) -> None:
        entry = event.node.data
        if entry is None:
            return
        self._highlighted_path = str(Path(entry.path).resolve())
        self._refresh_preview()

    @on(DirectoryTree.FileSelected, "#attachment-tree")
    def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self._highlighted_path = str(Path(event.path).resolve())
        self._toggle_current_selection()

    @on(Button.Pressed, "#attach-home")
    async def on_home_pressed(self, _event: Button.Pressed) -> None:
        await self.action_go_home()

    @on(Button.Pressed, "#attach-up")
    async def on_up_pressed(self, _event: Button.Pressed) -> None:
        await self.action_go_parent()

    @on(Button.Pressed, "#attach-go")
    async def on_go_pressed(self, _event: Button.Pressed) -> None:
        await self._apply_root_input()

    @on(Input.Submitted, "#attach-root")
    async def on_root_submitted(self, _event: Input.Submitted) -> None:
        await self._apply_root_input()

    async def _apply_root_input(self) -> None:
        root_input = self.query_one("#attach-root", Input)
        try:
            root = self._resolve_root_path(
                root_input.value, cwd=self._cwd, current_root=self._root
            )
        except ValueError as exc:
            self.query_one("#attach-preview", Static).update(
                Text(str(exc), style="#f1998e")
            )
            return
        await self._set_root_path(root)

    @on(Button.Pressed, "#attach-queue")
    def on_queue_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(sorted(self._selected_paths))

    @on(Button.Pressed, "#attach-clear")
    def on_clear_pressed(self, _event: Button.Pressed) -> None:
        self._selected_paths.clear()
        self._refresh_status()
        self._refresh_preview()

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
            yield Label("Setup iTE", classes="modal-title setup-title")
            yield Static(
                "Connect your provider credentials to start using iTE.",
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
                yield Button(
                    "👁",
                    id="setup-toggle-api-key",
                    variant="default",
                    classes="setup-eye",
                )
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
        base_url = (
            self.query_one("#setup-base-url", Input).value.strip() or DEFAULT_BASE_URL
        )
        api_key = (
            self.query_one("#setup-api-key", Input).value.strip() or DEFAULT_API_KEY
        )
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
