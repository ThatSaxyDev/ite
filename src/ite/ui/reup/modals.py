from __future__ import annotations

import os
import random
import re
import socket
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urlparse

import httpx
from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.theme import BUILTIN_THEMES
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)
from textual.widgets.directory_tree import DirEntry

from ite.attachments import MAX_ATTACHMENTS
from ite.auth import openrouter_pkce
from ite.client.llm_client import LLMClient
from ite.client.ollama_metadata import discover_context_window
from ite.config.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MODEL_NAME,
    Config,
)
from ite.config.loader import save_openrouter_oauth_secret
from ite.git.branches import BranchInfo, is_valid_branch_name
from ite.model_metadata import (
    format_context_window_label,
    parse_openrouter_model_metadata,
)
from ite.ui.reup.model_labels import (
    DEFAULT_REASONING_EFFORT,
    REASONING_LEVELS,
    bundled_model_display_label,
    reasoning_effort_display_label,
)

SETUP_PROVIDER_OLLAMA = "ollama"
SETUP_PROVIDER_OPENROUTER = "openrouter"
SETUP_PROVIDER_GENERIC = "generic"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_PREFERRED_MODEL = "stealth/ox-alpha"
SETUP_MODEL_OTHER = "__other__"
SETUP_MODEL_SELECT = "__select__"
RECOMMENDED_OLLAMA_MODELS: tuple[str, ...] = (
    "glm-5.3-flash:cloud",
    "glm-5.3:cloud",
    "deepseek-v4.1-flash:cloud",
    "minimax-m3:cloud",
    "kimi-k3:cloud",
    "gemma4:31b-cloud",
    "gpt-oss:20b-cloud",
    "kimi-k2.6:cloud",
    "minimax-m2.7:cloud",
)
HIDDEN_TEXTUAL_THEMES = {
    "ansi_dark",
    "ansi_light",
    "textual_ansi",
    "textual_ansi_dark",
    "textual_ansi_light",
}


def _openrouter_price_is_zero(value: Any) -> bool:
    """Return whether an OpenRouter pricing value represents a free rate."""
    if value is None or isinstance(value, bool):
        return False
    try:
        return Decimal(str(value).strip()) == 0
    except (InvalidOperation, ValueError):
        return False


def _is_free_openrouter_model(item: dict[str, Any], model_name: str) -> bool:
    """Recognize both legacy ``:free`` IDs and zero-priced preview models."""
    if model_name.endswith(":free"):
        return True
    pricing = item.get("pricing")
    if not isinstance(pricing, dict):
        return False
    return _openrouter_price_is_zero(pricing.get("prompt")) and _openrouter_price_is_zero(
        pricing.get("completion")
    )


def _supports_openrouter_agentic_tools(item: dict[str, Any]) -> bool:
    """Require tool support when OpenRouter provides capability metadata.

    The models endpoint is queried with ``supported_parameters=tools``. Some
    compatible responses omit ``supported_parameters`` entirely, so a missing
    field is treated as already filtered by the endpoint. When the field is
    present, enforce it locally as a safeguard against non-agentic models.
    """
    supported_parameters = item.get("supported_parameters")
    if supported_parameters is None:
        return True
    if not isinstance(supported_parameters, list):
        return False
    return "tools" in {
        str(parameter).strip().lower() for parameter in supported_parameters
    }


def is_hidden_textual_theme(name: str) -> bool:
    normalized = str(name or "").strip().lower().replace("-", "_")
    return normalized in HIDDEN_TEXTUAL_THEMES


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("enter", "accept", "Accept"),
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("1", "option_1", "Option 1"),
        ("2", "option_2", "Option 2"),
    ]

    def __init__(
        self,
        title: str,
        body: str,
        yes_label: str = "Approve",
        no_label: str = "Deny",
        primary: Literal["yes", "no"] = "yes",
    ) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._yes = yes_label
        self._no = no_label
        self._primary = primary
        self._left_result = primary != "yes"
        self._right_result = primary == "yes"

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal confirm-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._body, classes="modal-body confirm-body")
            with Horizontal(classes="modal-actions resume-actions confirm-actions"):
                if self._primary == "yes":
                    yield Button(
                        self._no,
                        id="no",
                        variant="default",
                        classes="confirm-secondary",
                    )
                    yield Button(
                        self._yes,
                        id="yes",
                        variant="success",
                        classes="confirm-primary",
                    )
                else:
                    yield Button(
                        self._yes,
                        id="yes",
                        variant="default",
                        classes="confirm-secondary",
                    )
                    yield Button(
                        self._no,
                        id="no",
                        variant="success",
                        classes="confirm-primary",
                    )

    async def on_mount(self) -> None:
        focus_id = "#yes" if self._primary == "yes" else "#no"
        self.query_one(focus_id, Button).focus()

    def action_accept(self) -> None:
        self.dismiss(self._primary == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def action_option_1(self) -> None:
        self.dismiss(self._left_result)

    def action_option_2(self) -> None:
        self.dismiss(self._right_result)

    @on(Button.Pressed, "#yes")
    def on_yes_pressed(self, _event: Button.Pressed) -> None:
        self.action_yes()

    @on(Button.Pressed, "#no")
    def on_no_pressed(self, _event: Button.Pressed) -> None:
        self.action_no()


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

    def _get_theme_colors(self) -> dict[str, str]:
        """Get theme-aware colors."""
        from ite.ui.reup.app import ReupApp

        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            return {
                "fg": styles.get("fg", "#dfe8f8"),
                "muted": styles.get("muted", "#8c93a1"),
                "success": styles.get("success", "#79d8a4"),
                "error": styles.get("error", "#f29b9b"),
                "primary": styles.get("primary", "#8fb7dc"),
                "secondary": styles.get("secondary", "#aeb7c6"),
                "warning": styles.get("warning", "#f2b38f"),
            }
        return {
            "fg": "#dfe8f8",
            "muted": "#8c93a1",
            "success": "#79d8a4",
            "error": "#f29b9b",
            "primary": "#8fb7dc",
            "secondary": "#aeb7c6",
            "warning": "#f2b38f",
        }

    def compose(self) -> ComposeResult:
        noun = "commit" if self._ahead_count == 1 else "commits"
        colors = self._get_theme_colors()
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
                    stats.append(f"{self._ahead_count} {noun}", style=f"bold {colors['fg']}")
                    stats.append("  ")
                    stats.append("↑", style=f"bold {colors['success']}")
                    if self._behind_count > 0:
                        stats.append("    ")
                        stats.append(
                            f"{self._behind_count} behind", style=f"bold {colors['warning']}"
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
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "toggle_voice_input", "Flow"),
    ]
    _AI_SPINNER_FRAMES = ("▰▱▱", "▱▰▱", "▱▱▰", "▱▰▱")
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

    def _get_theme_colors(self) -> dict[str, str]:
        """Get theme-aware colors."""
        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            return {
                "fg": styles.get("fg", "#dfe8f8"),
                "muted": styles.get("muted", "#8c93a1"),
                "success": styles.get("success", "#79d8a4"),
                "error": styles.get("error", "#f29b9b"),
                "primary": styles.get("primary", "#8fb7dc"),
                "secondary": styles.get("secondary", "#aeb7c6"),
            }
        return {
            "fg": "#dfe8f8",
            "muted": "#8c93a1",
            "success": "#79d8a4",
            "error": "#f29b9b",
            "primary": "#8fb7dc",
            "secondary": "#aeb7c6",
        }

    def _include_unstaged_text(self) -> Text:
        colors = self._get_theme_colors()
        text = Text()
        if self._include_unstaged:
            text.append("YES", style=f"bold {colors['success']}")
            text.append("  ")
            text.append("no", style=colors["muted"])
        else:
            text.append("yes", style=colors["muted"])
            text.append("  ")
            text.append("NO", style=f"bold {colors['error']}")
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
            "Return exactly one subject line using conventional commit format: type(scope): description. "
            "Type must be one of feat, fix, refactor, style, chore, docs, test, perf, ci, build. "
            "Write a descriptive subject that summarizes the intent, key changes, and user-visible effect. "
            "Include important details so the message stands on its own. "
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
        colors = self._get_theme_colors()
        status = Text()
        status.append(f"{frame} ", style=f"bold {colors['primary']}")
        status.append(message, style=f"italic {colors['secondary']}")
        return status

    def _idle_status_text(self) -> Text:
        colors = self._get_theme_colors()
        status = Text()
        status.append("✦ ", style=f"bold {colors['primary']}")
        status.append("draft with AI", style=colors["muted"])
        return status

    def _success_status_text(self) -> Text:
        colors = self._get_theme_colors()
        status = Text()
        status.append("✓ ", style=f"bold {colors['success']}")
        status.append("draft ready", style=colors["secondary"])
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
                    colors = self._get_theme_colors()
                    stats = Text()
                    file_label = (
                        f"{self._file_count} file"
                        if self._file_count == 1
                        else f"{self._file_count} files"
                    )
                    stats.append(file_label, style=f"bold {colors['fg']}")
                    stats.append("  ")
                    stats.append(f"+{self._additions}", style=f"bold {colors['success']}")
                    stats.append("  ")
                    stats.append(f"-{self._deletions}", style=f"bold {colors['error']}")
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
                    yield TextArea(
                        soft_wrap=True,
                        show_line_numbers=False,
                        highlight_cursor_line=False,
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
        self.query_one("#commit-message", TextArea).focus()
        self._update_commit_actions()
        self._set_ai_status_idle()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_toggle_voice_input(self) -> None:
        toggle = getattr(self.app, "action_toggle_voice_input", None)
        if callable(toggle):
            toggle()

    def _dismiss_with_action(self, action: str) -> None:
        message = self.query_one("#commit-message", TextArea).text.strip()
        if not message:
            self.query_one("#commit-message", TextArea).focus()
            return
        self.dismiss(
            {
                "action": action,
                "message": message,
                "include_unstaged": self._include_unstaged,
            }
        )

    def _update_commit_actions(self) -> None:
        has_message = bool(self.query_one("#commit-message", TextArea).text.strip())
        self.query_one("#commit-confirm", Button).disabled = not has_message
        self.query_one("#commit-push", Button).disabled = not has_message

    @on(events.Click, "#commit-include-unstaged-choice")
    def on_include_unstaged_choice_clicked(self, _event: events.Click) -> None:
        self._include_unstaged = not self._include_unstaged
        self.query_one("#commit-include-unstaged-choice", Static).update(
            self._include_unstaged_text()
        )

    @on(TextArea.Changed, "#commit-message")
    def on_commit_message_changed(self, _event: TextArea.Changed) -> None:
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
        input_widget = self.query_one("#commit-message", TextArea)
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
            input_widget.load_text(await self._generate_commit_message())
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


class VoiceSetupModal(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("enter", "submit", "Save"),
    ]

    def compose(self) -> ComposeResult:
        with Container(classes="modal voice-setup-modal"):
            yield Label("Flow", classes="modal-title")
            yield Static(
                "Add your own Groq API key for dictation in iTE. The key is saved in your local iTE config and is never shown in command history.",
                classes="modal-body",
            )
            yield Static("Groq API key", classes="voice-setup-label")
            yield Input(
                placeholder="gsk_...",
                password=True,
                id="voice-groq-api-key",
            )
            with Horizontal(classes="modal-actions resume-actions voice-setup-actions"):
                yield Button("Save", id="confirm", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        api_key = self.query_one("#voice-groq-api-key", Input)
        api_key.focus()
        self.call_after_refresh(api_key.focus)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        key = self.query_one("#voice-groq-api-key", Input).value.strip()
        if key:
            self.dismiss(key)

    @on(Input.Submitted, "#voice-groq-api-key")
    def on_key_submitted(self, _event: Input.Submitted) -> None:
        self.action_submit()

    @on(Button.Pressed, "#confirm")
    def on_save_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_submit()

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
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


class ModelPickerModal(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(
        self,
        current: str,
        models: list[dict[str, Any]],
        *,
        current_entry_id: str | None = None,
    ) -> None:
        super().__init__()
        self._current = current
        self._models = models
        self._current_entry_id = str(current_entry_id or "").strip()
        self._model_entry_ids: list[str] = []
        self._model_names: list[str] = []
        self._model_available: list[bool] = []
        self._model_unavailable_reasons: list[str] = []
        self._model_sources: list[str] = []
        self._model_saved_profile: list[bool] = []
        self._model_context_windows: list[int | None] = []

    @staticmethod
    def _empty_models_message() -> str:
        return (
            "No models available. Visit https://ite.kiishi.space/pricing to start "
            "iTE Pro for bundled cloud models, or run /setup to connect Ollama, "
            "OpenRouter, or another OpenAI-compatible provider."
        )

    @staticmethod
    def _model_count_label(count: int) -> str:
        return f"{count} model" if count == 1 else f"{count} models"

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal"):
            yield Label("Select model", classes="modal-title resume-title")
            yield Static(
                (
                    "Pick an available model, or remove a saved provider profile you no longer want to keep."
                    if self._models
                    else self._empty_models_message()
                ),
                classes="modal-body resume-body",
                id="model-picker-help",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="models", classes="resume-table", cursor_type="row")
            yield Label("", classes="modal-body", id="model-picker-refresh")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button(
                    "Remove saved", id="delete", variant="default", disabled=True
                )
                yield Button("Select", id="select", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#models", DataTable)
        for column in ("Model", "Source", "Context", "Capabilities", "Status", "Current"):
            table.add_column(column)
        self._populate_table(table)
        refresh_label = self.query_one("#model-picker-refresh", Label)
        refresh_label.update(self._model_count_label(len(self._model_names)))

    def _populate_table(self, table: DataTable) -> None:
        table.clear()
        self._model_entry_ids = []
        self._model_names = []
        self._model_available = []
        self._model_unavailable_reasons = []
        self._model_sources = []
        self._model_saved_profile = []
        self._model_context_windows = []
        self._model_capabilities = []
        for item in self._models:
            model_name = str(item.get("model_name") or "").strip()
            label = str(item.get("label") or model_name).strip()
            provider = str(item.get("provider") or "").strip()
            available = bool(item.get("available", True))
            unavailable_reason = str(item.get("unavailable_reason") or "").strip()
            saved_profile = bool(item.get("saved_profile", False))
            context_window = item.get("context_window")
            capabilities = item.get("capabilities")
            entry_id = str(item.get("entry_id") or model_name).strip()
            if not model_name:
                continue
            self._model_entry_ids.append(entry_id)
            self._model_names.append(model_name)
            self._model_available.append(available)
            self._model_unavailable_reasons.append(unavailable_reason)
            self._model_sources.append(provider)
            self._model_saved_profile.append(saved_profile)
            self._model_context_windows.append(
                int(context_window)
                if isinstance(context_window, int) and context_window > 0
                else None
            )
            self._model_capabilities.append(
                capabilities if isinstance(capabilities, list) else None
            )
            table.add_row(
                label,
                provider,
                format_context_window_label(self._model_context_windows[-1]),
                ", ".join(str(c) for c in self._model_capabilities[-1]) if self._model_capabilities[-1] else "",
                "Available" if available else "Unavailable",
                "✓"
                if (
                    entry_id == self._current_entry_id
                    if self._current_entry_id
                    else model_name == self._current
                )
                else "",
            )
        if self._model_names:
            initial_row = 0
            if self._current_entry_id and self._current_entry_id in self._model_entry_ids:
                initial_row = self._model_entry_ids.index(self._current_entry_id)
            elif self._current in self._model_names:
                initial_row = self._model_names.index(self._current)
            table.move_cursor(row=initial_row, column=0)
            self._refresh_selection_state(initial_row)

    def update_models(
        self, models: list[dict[str, Any]], *, current_entry_id: str = ""
    ) -> None:
        """Refresh the model list in-place while the modal is open."""
        self._models = models
        if current_entry_id:
            self._current_entry_id = current_entry_id
        table = self.query_one("#models", DataTable)
        self._populate_table(table)
        refresh_label = self.query_one("#model-picker-refresh", Label)
        refresh_label.update(self._model_count_label(len(self._model_names)))
        if not self._model_names:
            self.query_one("#model-picker-help", Static).update(
                self._empty_models_message()
            )

    def _refresh_selection_state(self, row: int) -> None:
        select_button = self.query_one("#select", Button)
        delete_button = self.query_one("#delete", Button)
        help_text = self.query_one("#model-picker-help", Static)
        if not (0 <= row < len(self._model_names)):
            select_button.disabled = True
            delete_button.disabled = True
            help_text.update(
                self._empty_models_message()
                if not self._model_names
                else "Pick an available model, or remove a saved provider profile."
            )
            return

        available = self._model_available[row]
        select_button.disabled = not available
        delete_button.disabled = not self._model_saved_profile[row]
        if available:
            help_text.update(
                "Pick an available model, or remove a saved provider profile."
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
        if (
            0 <= event.cursor_row < len(self._model_names)
            and self._model_available[event.cursor_row]
        ):
            self.dismiss(
                {
                    "action": "select",
                    "entry_id": self._model_entry_ids[event.cursor_row],
                    "model_name": self._model_names[event.cursor_row],
                    "source_kind": self._model_entry_ids[event.cursor_row].split(":", 1)[0],
                }
            )

    @on(Button.Pressed, "#select")
    def on_select_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#models", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._model_names) and self._model_available[row]:
            self.dismiss(
                {
                    "action": "select",
                    "entry_id": self._model_entry_ids[row],
                    "model_name": self._model_names[row],
                    "source_kind": self._model_entry_ids[row].split(":", 1)[0],
                }
            )

    @on(Button.Pressed, "#delete")
    def on_delete_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#models", DataTable)
        row = table.cursor_row
        if (
            0 <= row < len(self._model_names)
            and self._model_saved_profile[row]
        ):
            self.dismiss(
                {
                    "action": "delete",
                    "entry_id": self._model_entry_ids[row],
                    "model_name": self._model_names[row],
                    "source_kind": self._model_entry_ids[row].split(":", 1)[0],
                }
            )

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ApprovalPickerModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    _MODE_DESCRIPTIONS: dict[str, str] = {
        "on_request": "Ask before every mutating action",
        "on_failure": "Auto-approve, ask only on failure",
        "auto": "Auto-approve all safe operations",
        "auto_edit": "Auto-approve edits, confirm commands",
        "never": "Only allow safe commands, reject all else",
        "yolo": "Approve everything — no guardrails",
    }

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current
        from ite.config.config import ApprovalPolicy

        self._modes = [p.value for p in ApprovalPolicy]

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal approval-picker-modal"):
            yield Label("Select approval mode", classes="modal-title resume-title")
            yield Static(
                "Choose when iTE should ask for approval before running commands.",
                classes="modal-body resume-body",
                id="approval-picker-help",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="approvals", classes="resume-table", cursor_type="row")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Select", id="select", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#approvals", DataTable)
        table.add_columns("Mode", "Description", "Current")
        initial_row = 0
        for index, mode in enumerate(self._modes):
            table.add_row(
                mode,
                self._MODE_DESCRIPTIONS.get(mode, ""),
                "✓" if mode == self._current else "",
            )
            if mode == self._current:
                initial_row = index
        if self._modes:
            table.move_cursor(row=initial_row, column=0)

    @on(DataTable.RowSelected, "#approvals")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self._modes):
            self.dismiss(self._modes[event.cursor_row])

    @on(Button.Pressed, "#select")
    def on_select_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#approvals", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._modes):
            self.dismiss(self._modes[row])

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ThemePickerModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current
        self._theme_names = sorted(
            name for name in BUILTIN_THEMES.keys() if not is_hidden_textual_theme(name)
        )

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
            table.add_row(
                name,
                "Dark" if theme.dark else "Light",
                "✓" if name == self._current else "",
            )
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


class ThinkingLevelModal(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, current: str, *, model_label: str) -> None:
        super().__init__()
        self._current = str(current or "").strip().lower() or DEFAULT_REASONING_EFFORT
        self._model_label = str(model_label or "Model").strip()

    def compose(self) -> ComposeResult:
        with Container(classes="modal resume-modal thinking-level-modal"):
            yield Label(
                f"Thinking Level for {self._model_label}",
                classes="modal-title resume-title",
            )
            yield Static(
                "Choose how much the model reasons before responding.",
                classes="modal-body resume-body",
                id="thinking-level-help",
            )
            with Container(classes="modal-list resume-list"):
                yield DataTable(
                    id="thinking-levels", classes="resume-table", cursor_type="row"
                )
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Select", id="select", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")
    async def on_mount(self) -> None:
        table = self.query_one("#thinking-levels", DataTable)
        table.add_columns("Level", "Description", "Current")
        initial_row = 0
        for index, (wire_value, label, description) in enumerate(REASONING_LEVELS):
            table.add_row(
                label,
                description,
                "✓" if wire_value == self._current else "",
            )
            if wire_value == self._current:
                initial_row = index
        if REASONING_LEVELS:
            table.move_cursor(row=initial_row, column=0)

    def action_cursor_up(self) -> None:
        table = self.query_one("#thinking-levels", DataTable)
        table.action_cursor_up()

    def action_cursor_down(self) -> None:
        table = self.query_one("#thinking-levels", DataTable)
        table.action_cursor_down()

    def action_select(self) -> None:
        table = self.query_one("#thinking-levels", DataTable)
        self._dismiss_row(table.cursor_row)

    def _dismiss_row(self, row: int) -> None:
        if 0 <= row < len(REASONING_LEVELS):
            self.dismiss(REASONING_LEVELS[row][0])

    @on(DataTable.RowSelected, "#thinking-levels")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        self._dismiss_row(event.cursor_row)

    @on(Button.Pressed, "#select")
    def on_select_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#thinking-levels", DataTable)
        self._dismiss_row(table.cursor_row)

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class UsageSummaryModal(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, summary: dict[str, Any] | None, *, loading: bool = False) -> None:
        super().__init__()
        self._summary = summary
        self._loading = loading and summary is None
        self._unavailable = False

    @staticmethod
    def _remaining_percent(used: float, cap: float) -> int:
        cap = max(1.0, cap)
        return max(0, min(100, int(((cap - used) / cap) * 100)))

    def _window_fallback_reset(self, label: str) -> datetime:
        now = datetime.now().astimezone()
        if label == "5h":
            return now + timedelta(hours=5)
        if label == "Weekly":
            return now + timedelta(days=7)
        return now + timedelta(days=30)

    def _format_reset_time(self, value: str, label: str) -> str:
        try:
            dt = (
                datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
                if value
                else self._window_fallback_reset(label)
            )
        except ValueError:
            dt = self._window_fallback_reset(label)
        if label == "5h":
            time_str = dt.strftime('%I:%M%p').lstrip('0').lower()
            return time_str
        day_str = str(dt.day)
        time_str = dt.strftime('%I:%M%p').lstrip('0').lower()
        return f"{dt.strftime('%B')} {day_str} at {time_str}"

    def _build_window_label(self, label: str, reset_time: str, fg: str, muted: str) -> Text:
        text = Text()
        text.append(label, style=f"bold {fg}")
        text.append(" | ", style=muted)
        text.append(reset_time, style=muted)
        return text

    _bar_width: int = 92

    def _compute_bar_width(self) -> None:
        try:
            body = self.query_one("#usage-summary-body", Static)
            w = body.size.width
            if w > 0:
                self._bar_width = w
        except Exception:
            pass

    def _build_bar(self, remaining_percent: int) -> Text:
        used_percent = max(0, min(100, 100 - remaining_percent))
        filled = max(0, min(self._bar_width, round((used_percent / 100) * self._bar_width)))
        empty = max(0, self._bar_width - filled)
        bar = Text()
        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            filled_color = styles.get("success", "#8AD4A1")
            empty_color = styles.get("disabled", "#3a3a3f")
        else:
            filled_color = "#8AD4A1"
            empty_color = "#3a3a3f"
        line = Text()
        if filled:
            line.append("█" * filled, style=f"bold {filled_color}")
        if empty:
            line.append("█" * empty, style=empty_color)
        bar.append(line)
        return bar

    def _build_renderable(self) -> Group:
        sections: list[object] = []
        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            fg = styles.get("fg", "#f3f4f6")
            muted = styles.get("muted", "#8f949d")
        else:
            fg = "#f3f4f6"
            muted = "#8f949d"

        if self._unavailable:
            return Group(
                Text("Usage is not available right now.", style=f"bold {fg}"),
                Text("Try again in a moment.", style=muted),
            )
        if self._loading or not self._summary:
            return Group(
                Text("Loading usage...", style=f"bold {fg}"),
                Text("Fetching the latest bundled usage windows.", style=muted),
            )

        quotas = self._summary.get("quotas") or {}
        quota_rows = (
            ("5h", "fiveHour"),
            ("Weekly", "sevenDay"),
            ("Monthly", "thirtyDay"),
        )
        for index, (label, key) in enumerate(quota_rows):
            quota = quotas.get(key) or {}
            used = float(quota.get("usedUsdCents") or 0)
            cap = max(1.0, float(quota.get("capUsdCents") or 1))
            remaining = self._remaining_percent(used, cap)
            reset_time = self._format_reset_time(str(quota.get("fullWindowClearAt") or quota.get("nextResetAt") or ""), label)

            row = Table.grid(expand=True)
            row.add_column(ratio=1)
            row.add_column(justify="right", width=18)
            row.add_row(
                self._build_window_label(label, reset_time, fg, muted),
                Text(f"{remaining}% remaining", style=f"bold {fg}"),
            )
            sections.append(row)
            sections.append(Text(""))
            sections.append(self._build_bar(remaining))
            if index < len(quota_rows) - 1:
                sections.append(Text(""))

        return Group(*sections)

    def on_mount(self) -> None:
        self._compute_bar_width()
        self._refresh_body()

    def on_resize(self, _event: events.Resize) -> None:
        self._compute_bar_width()
        self._refresh_body()

    def _refresh_body(self) -> None:
        try:
            self.query_one("#usage-summary-body", Static).update(self._build_renderable())
        except Exception:
            return

    def update_summary(self, summary: dict[str, Any]) -> None:
        self._summary = summary
        self._loading = False
        self._unavailable = False
        self._refresh_body()

    def mark_unavailable(self) -> None:
        self._loading = False
        if self._summary:
            self._refresh_body()
            return
        self._unavailable = True
        self._refresh_body()

    def compose(self) -> ComposeResult:
        with Container(classes="modal usage-modal"):
            yield Label("Usage", classes="modal-title")
            with Container(classes="usage-summary-panel"):
                yield Static(
                    self._build_renderable(),
                    id="usage-summary-body",
                    classes="usage-summary-body",
                )
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

    _bar_width: int = 92

    def _compute_bar_width(self) -> None:
        try:
            body = self.query_one(".usage-summary-body", Static)
            w = body.size.width
            if w > 0:
                self._bar_width = w
        except Exception:
            pass

    def _build_bar(self, used_percent: float) -> Text:
        normalized = max(0, min(100, round(used_percent)))
        filled = max(0, min(self._bar_width, round((normalized / 100) * self._bar_width)))
        empty = max(0, self._bar_width - filled)
        bar = Text()
        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            filled_color = styles.get("success", "#8AD4A1")
            empty_color = styles.get("disabled", "#3a3a3f")
        else:
            filled_color = "#8AD4A1"
            empty_color = "#3a3a3f"
        line = Text()
        if filled:
            line.append("█" * filled, style=f"bold {filled_color}")
        if empty:
            line.append("█" * empty, style=empty_color)
        bar.append(line)
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

        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            fg = styles.get("fg", "#f3f4f6")
            muted = styles.get("muted", "#d1d5db")
            dim = styles.get("disabled", "#8f949d")
        else:
            fg = "#f3f4f6"
            muted = "#d1d5db"
            dim = "#8f949d"

        summary = Table.grid(expand=True)
        summary.add_column(ratio=1)
        summary.add_column(justify="right", width=22)
        summary.add_row(
            Text("Current context", style=f"bold {fg}"),
            Text(f"{latest_tokens:,}/{context_window:,} tokens", style=f"bold {fg}"),
        )
        summary.add_row(
            Text(
                f"{used_pct:.1f}% used",
                style=f"bold {muted}",
            ),
            Text(
                f"Auto-compact at {trigger_pct:.1f}%",
                style=dim,
            ),
        )
        return Group(summary, Text(""), self._build_bar(used_pct))

    def _refresh_body(self) -> None:
        try:
            self.query_one(".usage-summary-body", Static).update(self._build_renderable())
        except Exception:
            return

    def on_mount(self) -> None:
        self._compute_bar_width()
        self._refresh_body()

    def on_resize(self, _event: events.Resize) -> None:
        self._compute_bar_width()
        self._refresh_body()

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

    def _get_theme_colors(self) -> dict[str, str]:
        """Get theme-aware colors."""
        from ite.ui.reup.app import ReupApp
        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            return {
                "fg": styles.get("fg", "#f3f4f6"),
                "muted": styles.get("muted", "#8f949d"),
                "border": styles.get("border", "#2a2d31"),
            }
        return {"fg": "#f3f4f6", "muted": "#8f949d", "border": "#2a2d31"}

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
            "billing.access_granted": "Pro access granted",
            "billing.subscription_updated": "Billing updated",
            "billing.subscription_synced": "Billing synced",
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
            return f"{bundled_model_display_label(model)} · {window}"
        if isinstance(model, str):
            return bundled_model_display_label(model)
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
        colors = self._get_theme_colors()
        fg = colors["fg"]
        muted = colors["muted"]
        border = colors["border"]

        if not isinstance(totals, dict):
            return Group(Text("No bundled usage yet.", style=muted))

        current_period = self._analytics.get("currentPeriod")
        if not isinstance(current_period, dict):
            current_period = {"start": None, "end": None}

        top = Table.grid(expand=True)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_row(
            Text("Today", style=muted),
            Text("7 days", style=muted),
            Text("Billing period", style=muted),
            Text("All time", style=muted),
        )
        top.add_row(
            Text(
                self._format_usd(int(totals.get("todayUsdCents") or 0)),
                style=f"bold {fg}",
            ),
            Text(
                self._format_usd(int(totals.get("sevenDayUsdCents") or 0)),
                style=f"bold {fg}",
            ),
            Text(
                self._format_usd(int(totals.get("currentPeriodUsdCents") or 0)),
                style=f"bold {fg}",
            ),
            Text(
                self._format_usd(int(totals.get("allTimeUsdCents") or 0)),
                style=f"bold {fg}",
            ),
        )
        top.add_row(
            Text(
                self._format_ngn(int(totals.get("todayUsdCents") or 0)), style=muted
            ),
            Text(
                self._format_ngn(int(totals.get("sevenDayUsdCents") or 0)),
                style=muted,
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
                style=muted,
            ),
            Text(
                f"{self._format_ngn(int(totals.get('allTimeUsdCents') or 0))}  ·  {int(totals.get('allTimeRequestCount') or 0)} requests",
                style=muted,
            ),
        )

        by_model = self._analytics.get("byModel")
        model_table = Table.grid(expand=True)
        model_table.add_column(ratio=1)
        model_table.add_column(justify="right", width=14)
        model_table.add_column(justify="right", width=16)
        if isinstance(by_model, list) and by_model:
            model_table.add_row(
                Text("Model", style=muted),
                Text("Spend", style=muted),
                Text("Share", style=muted),
            )
            for row in by_model[:3]:
                if not isinstance(row, dict):
                    continue
                model_table.add_row(
                    Text(
                        self._model_label(str(row.get("modelKey") or "")),
                        style=fg,
                    ),
                    Text(
                        self._format_usd(int(row.get("usdCents") or 0)), style=fg
                    ),
                    Text(
                        f"{self._format_ngn(int(row.get('usdCents') or 0))}  ·  {int(row.get('sharePercent') or 0)}%",
                        style=muted,
                    ),
                )
        else:
            model_table.add_row(
                Text("No model spend yet.", style=muted), Text(""), Text("")
            )

        return Group(
            top,
            Rule(style=border),
            Text("Top models", style=f"bold {fg}"),
            model_table,
        )

    @staticmethod
    def _model_label(model_key: str) -> str:
        mapping = {
            "kimi-k2.5": "Kimi K2.5",
            "kimi-k2.6": "Kimi K2.6",
            "minimax-m2.5": "MiniMax M2.5",
            "minimax-m2.7": "MiniMax M2.7",
            "minimax-m3": "MiniMax M3",
            "glm-5": "GLM-5",
            "glm-5.1": "GLM-5.1",
        }
        return bundled_model_display_label(model_key, mapping.get(model_key, model_key))

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


class DayActivityModal(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, cell_date: date, tokens: dict[date, int]) -> None:
        super().__init__()
        self._cell_date = cell_date
        self._tokens = tokens

    @staticmethod
    def _format_count(value: int) -> str:
        return f"{value:,}"

    def _get_theme_colors(self) -> dict[str, str]:
        from ite.ui.reup.app import ReupApp

        app = self.app
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            return {
                "fg": styles.get("fg", "#f3f4f6"),
                "muted": styles.get("muted", "#8f949d"),
                "success": styles.get("success", "#8AD4A1"),
            }
        return {"fg": "#f3f4f6", "muted": "#8f949d", "success": "#8AD4A1"}

    def _title(self) -> str:
        day = self._cell_date
        return f"{day.strftime('%A, %B')} {day.day}, {day.year}"

    def _build_renderable(self) -> Group:
        colors = self._get_theme_colors()
        fg = colors["fg"]
        muted = colors["muted"]
        success = colors["success"]

        amount = self._tokens.get(self._cell_date, 0)
        today = date.today()

        if self._cell_date == today:
            rel = "today"
        elif self._cell_date == today - timedelta(days=1):
            rel = "yesterday"
        else:
            rel = self._cell_date.strftime("%A").lower()

        active = [v for d, v in self._tokens.items() if d <= today and v > 0]
        peak = max(active, default=0)
        total = sum(active)
        is_peak = amount > 0 and amount == peak

        sections: list[object] = [
            Text(self._format_count(amount), style=f"bold {fg}"),
            Text("tokens used on this day", style=muted),
            Text(""),
        ]

        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        grid.add_row(Text("Day", style=muted), Text(rel, style=fg))
        if is_peak:
            grid.add_row(
                Text("Highlight", style=muted),
                Text("busiest day", style=f"bold {success}"),
            )
        if active and amount > 0 and len(active) > 1:
            rank = sorted(active, reverse=True).index(amount) + 1
            grid.add_row(
                Text("Rank", style=muted),
                Text(f"#{rank} of {len(active)} active days", style=fg),
            )
        if peak > 0:
            grid.add_row(
                Text("Share of peak", style=muted),
                Text(f"{round(amount / peak * 100)}%", style=fg),
            )
        if total > 0:
            grid.add_row(
                Text("Share of window", style=muted),
                Text(f"{round(amount / total * 100, 1):.1f}%", style=fg),
            )
        sections.append(grid)
        return Group(*sections)

    def on_mount(self) -> None:
        self._refresh_body()

    def _refresh_body(self) -> None:
        try:
            self.query_one(".usage-summary-body", Static).update(
                self._build_renderable()
            )
        except Exception:
            return

    def compose(self) -> ComposeResult:
        with Container(classes="modal activity-modal"):
            yield Label(self._title(), classes="modal-title")
            yield Static(
                "Token usage recorded for this day.", classes="modal-body"
            )
            with Container(classes="usage-summary-panel"):
                yield Static(self._build_renderable(), classes="usage-summary-body")
            with Horizontal(classes="modal-actions"):
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
        def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
            """Filter out hidden paths (those starting with a dot)."""
            return [p for p in paths if not p.name.startswith(".")]

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
        # Use theme-aware colors via app
        app = self.app
        # Local import to avoid circular dependency
        from ite.ui.reup.app import ReupApp
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            tone = styles.get("success", "#4edea3") if count <= MAX_ATTACHMENTS else styles.get("warning", "#ffb95f")
        else:
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
        # Use theme-aware muted color via app
        app = self.app
        # Local import to avoid circular dependency
        from ite.ui.reup.app import ReupApp
        if isinstance(app, ReupApp):
            styles = app._render_styles()
            muted = styles.get("muted", "#8c97ab")
        else:
            muted = "#8c97ab"
        if not self._highlighted_path:
            preview.update(
                Text("Navigate the tree, press space to select files.", style=muted)
            )
            return
        path = Path(self._highlighted_path)
        kind = "directory" if path.is_dir() else "file"
        selected = self._path_key(path) in self._selected_paths
        status = "selected" if selected else "not selected"
        preview.update(Text(f"{path}  •  {kind}  •  {status}", style=muted))

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


class SetupModal(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._validating = False
        self._openrouter_models: list[str] = []
        self._openrouter_context_windows: dict[str, int] = {}
        self._ollama_context_windows: dict[str, int | None] = {}
        self._ollama_context_pending: set[str] = set()
        self._ollama_context_display_model: str | None = None
        self._ollama_manual_context_windows: dict[str, str] = {}
        self._openrouter_headless: bool = False
        self._openrouter_signin_in_flight: bool = False
        self._openrouter_signed_in: bool = False
        self._pending_pkce: openrouter_pkce.PKCEPair | None = None
        inferred_provider = self._infer_provider()
        current_model = str(self._config.model_name or DEFAULT_MODEL_NAME).strip()
        self._provider_selected_model: dict[str, str] = {
            SETUP_PROVIDER_OLLAMA: (
                current_model
                if inferred_provider == SETUP_PROVIDER_OLLAMA
                and current_model in RECOMMENDED_OLLAMA_MODELS
                else RECOMMENDED_OLLAMA_MODELS[0]
            ),
            SETUP_PROVIDER_OPENROUTER: (
                current_model if inferred_provider == SETUP_PROVIDER_OPENROUTER else ""
            ),
            SETUP_PROVIDER_GENERIC: (
                current_model if inferred_provider == SETUP_PROVIDER_GENERIC else ""
            ),
        }
        self._provider_manual_model: dict[str, str] = {
            SETUP_PROVIDER_OLLAMA: (
                current_model
                if inferred_provider == SETUP_PROVIDER_OLLAMA
                and current_model not in RECOMMENDED_OLLAMA_MODELS
                else ""
            ),
            SETUP_PROVIDER_OPENROUTER: (
                current_model if inferred_provider == SETUP_PROVIDER_OPENROUTER else ""
            ),
            SETUP_PROVIDER_GENERIC: (
                current_model if inferred_provider == SETUP_PROVIDER_GENERIC else ""
            ),
        }
        self._active_provider = inferred_provider
        context_source = str(config.model.context_window_source or "").strip()
        known_context = (
            str(config.model.context_window)
            if config.model.context_window > 0
            and context_source not in {"provider_fixed_default", "fallback_default"}
            and (context_source or config.model.context_window != DEFAULT_CONTEXT_WINDOW)
            else ""
        )
        self._provider_context_window: dict[str, str] = {
            provider: known_context if provider == inferred_provider else ""
            for provider in (SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC)
        }

    def _infer_provider(self) -> str:
        base_url = str(self._config.base_url or "").strip().lower()
        api_key = str(self._config.api_key or "").strip().lower()
        if (
            not base_url
            or "localhost:11434" in base_url
            or "127.0.0.1:11434" in base_url
        ):
            return SETUP_PROVIDER_OLLAMA
        if "openrouter.ai" in base_url:
            return SETUP_PROVIDER_OPENROUTER
        if api_key == DEFAULT_API_KEY and not base_url:
            return SETUP_PROVIDER_OLLAMA
        return SETUP_PROVIDER_GENERIC

    def _provider_defaults(self, provider: str) -> tuple[str, str, str]:
        current_model = self._config.model_name or DEFAULT_MODEL_NAME
        if provider == SETUP_PROVIDER_OLLAMA:
            return (
                self._config.base_url or DEFAULT_BASE_URL,
                self._config.api_key or DEFAULT_API_KEY,
                current_model,
            )
        if provider == SETUP_PROVIDER_OPENROUTER:
            return (
                self._config.base_url
                if "openrouter.ai" in str(self._config.base_url or "").lower()
                else OPENROUTER_BASE_URL,
                ""
                if str(self._config.api_key or "").strip().lower() == DEFAULT_API_KEY
                else (self._config.api_key or ""),
                current_model,
            )
        return (
            self._config.base_url or "",
            ""
            if str(self._config.api_key or "").strip().lower() == DEFAULT_API_KEY
            else (self._config.api_key or ""),
            self._provider_manual_model.get(SETUP_PROVIDER_GENERIC, ""),
        )

    def _provider_copy(self, provider: str) -> tuple[str, str, str]:
        if provider == SETUP_PROVIDER_OLLAMA:
            return (
                "Use a model through Ollama.",
                "Choose a recommended cloud model, or pick Other to enter a local or cloud model. Start Ollama and sign in for cloud access. Cloud usage depends on your plan and available credits.",
                "Enter the exact model name as Ollama expects it.",
            )
        if provider == SETUP_PROVIDER_OPENROUTER:
            return (
                "",
                "Enter your OpenRouter key. iTE will verify it",
                "Enter the exact model id OpenRouter expects.",
            )
        return (
            "Use any OpenAI-compatible provider.",
            "Enter your provider base URL and API key. iTE will verify the connection before saving this setup.",
            "Enter the exact model name your provider expects.",
        )

    @staticmethod
    def _resolve_setup_api_key(provider: str, api_key: str) -> str:
        return str(api_key or "").strip()

    def _selected_model_name(self, provider: str) -> str:
        if provider == SETUP_PROVIDER_GENERIC:
            return self.query_one("#setup-model-input", Input).value.strip()
        selected_model = str(
            self.query_one("#setup-model-select", Select).value or ""
        ).strip()
        if selected_model == SETUP_MODEL_OTHER:
            return self.query_one("#setup-model-input", Input).value.strip()
        if selected_model in {"", SETUP_MODEL_SELECT}:
            return ""
        return selected_model

    def _resolved_setup_context_window(self, provider: str) -> int | None:
        model_name = self._selected_model_name(provider)
        if not model_name:
            return None
        if provider == SETUP_PROVIDER_OPENROUTER:
            return self._openrouter_context_windows.get(model_name)
        if provider == SETUP_PROVIDER_OLLAMA and self._ollama_listed_selection():
            detected = self._ollama_context_windows.get(model_name)
            if detected:
                return detected
        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}:
            field = self._safe_query_one("#setup-context-window", Input)
            value = (
                field.value
                if field is not None
                else self._provider_context_window.get(provider, "")
            )
            return self._parse_context_window(value)
        if model_name == str(self._config.model_name or "").strip():
            current = int(self._config.model.context_window or 0)
            return current if current > 0 else None
        return None

    def _resolved_setup_context_source(self, provider: str) -> str:
        model_name = self._selected_model_name(provider)
        if not model_name:
            if provider == SETUP_PROVIDER_OPENROUTER and not self._openrouter_models:
                return "unknown_until_provider_load"
            return "unknown"
        if provider == SETUP_PROVIDER_OPENROUTER:
            return (
                "resolved_from_openrouter"
                if model_name in self._openrouter_context_windows
                else "unknown_until_provider_load"
            )
        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}:
            if (
                provider == SETUP_PROVIDER_OLLAMA
                and self._ollama_listed_selection()
                and self._ollama_context_windows.get(model_name)
            ):
                return "ollama_model_api"
            return "user_configured"
        existing = str(getattr(self._config.model, "context_window_source", "") or "").strip()
        if model_name == str(self._config.model_name or "").strip() and existing:
            return existing
        return "unknown_until_provider_verification"

    def _update_model_help_text(self, provider: str) -> None:
        self._refresh_ollama_context_field(provider)
        _provider_copy, _provider_help, base_model_help = self._provider_copy(provider)
        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}:
            self.query_one("#setup-model-help", Static).update(base_model_help)
            return
        context_window = self._resolved_setup_context_window(provider)
        source = self._resolved_setup_context_source(provider)
        if context_window:
            if source == "resolved_from_openrouter":
                suffix = (
                    f"\nContext window: {format_context_window_label(context_window)} "
                    "(resolved from OpenRouter)"
                )
            elif source == "provider_fixed_default":
                suffix = f"\nContext window: {format_context_window_label(context_window)}"
            elif source == "bundled_provider_api":
                suffix = (
                    f"\nContext window: {format_context_window_label(context_window)} "
                    "(resolved from bundled provider)"
                )
            elif source == "saved_config":
                suffix = (
                    f"\nContext window: {format_context_window_label(context_window)} "
                    "(restored from saved config)"
                )
            else:
                suffix = (
                    f"\nContext window: {format_context_window_label(context_window)}"
                )
        else:
            if source == "unknown_until_provider_load":
                suffix = "\nContext window: unknown until models are loaded from the provider."
            elif source == "unknown_until_provider_verification":
                suffix = "\nContext window: unknown until provider verification."
            else:
                suffix = "\nContext window: unknown."
        self.query_one("#setup-model-help", Static).update(base_model_help + suffix)

    def compose(self) -> ComposeResult:
        provider = self._infer_provider()
        base_url, api_key, model_name = self._provider_defaults(provider)
        provider_copy, provider_help, model_help = self._provider_copy(provider)
        if provider == SETUP_PROVIDER_OLLAMA:
            model_options = [(model, model) for model in RECOMMENDED_OLLAMA_MODELS]
            model_value = (
                model_name
                if model_name in RECOMMENDED_OLLAMA_MODELS
                else RECOMMENDED_OLLAMA_MODELS[0]
            )
        elif provider == SETUP_PROVIDER_OPENROUTER:
            model_options = [("Select a model", SETUP_MODEL_SELECT)]
            model_value = SETUP_MODEL_SELECT
        else:
            model_options = [(model_name, model_name)] if model_name else []
            model_value = model_name or SETUP_MODEL_OTHER
        with Container(classes="modal setup-modal"):
            yield Label("Setup iTE", classes="modal-title setup-title")
            yield Static(
                "Choose how iTE should reach your model.",
                classes="modal-body setup-body",
            )
            yield Static("Provider", classes="setup-label")
            yield Select(
                [
                    ("Ollama on this computer", SETUP_PROVIDER_OLLAMA),
                    ("OpenRouter", SETUP_PROVIDER_OPENROUTER),
                    ("Other OpenAI-compatible provider", SETUP_PROVIDER_GENERIC),
                ],
                value=provider,
                allow_blank=False,
                id="setup-provider",
            )
            yield Static(provider_copy, id="setup-provider-copy", classes="setup-help")
            yield Static(
                "Connected to OpenRouter",
                id="openrouter-connected-label",
                classes="setup-label",
            )
            yield Static("Base URL", classes="setup-label", id="setup-base-url-label")
            yield Input(
                value=base_url,
                placeholder=DEFAULT_BASE_URL,
                id="setup-base-url",
            )
            yield Static(provider_help, id="setup-base-url-help", classes="setup-help")
            yield Static("API key", classes="setup-label", id="setup-api-key-label")
            with Horizontal(classes="setup-secret-row", id="setup-api-key-row"):
                yield Input(
                    value=api_key,
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
            yield Static("or", id="setup-openrouter-or", classes="setup-or")
            yield Button(
                "Sign in with OpenRouter",
                id="setup-openrouter-signin",
                variant="success",
                classes="setup-openrouter-signin",
            )
            yield Static(
                "",
                id="openrouter-auth-code-label",
                classes="setup-label",
            )
            yield Input(
                value="",
                placeholder="Paste the authorization code…",
                password=True,
                id="openrouter-auth-code",
            )
            with Horizontal(
                classes="setup-openrouter-actions", id="openrouter-actions"
            ):
                yield Button(
                    "View / revoke key on OpenRouter",
                    id="openrouter-manage",
                    variant="default",
                )
                yield Button(
                    "Sign out",
                    id="openrouter-signout",
                    variant="error",
                )
            yield Static("Model", classes="setup-label", id="setup-model-label")
            with Horizontal(classes="setup-model-row", id="setup-model-select-row"):
                yield Select(
                    model_options + [("Other", SETUP_MODEL_OTHER)],
                    value=model_value,
                    allow_blank=False,
                    id="setup-model-select",
                )
                yield Button(
                    "Load",
                    id="setup-load-models",
                    variant="default",
                    classes="setup-load-models",
                )
            yield Input(
                value=model_name,
                placeholder="Model",
                id="setup-model-input",
            )
            yield Static(model_help, id="setup-model-help", classes="setup-help")
            yield Static(
                "Context window (tokens)",
                id="setup-context-window-label",
                classes="setup-label",
            )
            yield Input(
                value=self._provider_context_window.get(provider, ""),
                placeholder="e.g. 1000000",
                id="setup-context-window",
            )
            yield Static(
                "Enter the token limit available for this model. iTE uses it to time compaction. For Ollama, use the context configured on the server.",
                id="setup-context-window-help",
                classes="setup-help",
            )
            yield Static("", id="setup-status", classes="setup-status")
            yield Static("", id="setup-error", classes="setup-error")
            with Horizontal(classes="modal-actions setup-actions"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Continue", id="continue", variant="primary")

    async def on_mount(self) -> None:
        provider = self._infer_provider()
        self._active_provider = provider
        context_field = self._safe_query_one("#setup-context-window", Input)
        if context_field is not None:
            context_field.value = self._provider_context_window.get(provider, "")
        provider_copy, _provider_help, _model_help = self._provider_copy(provider)
        self.query_one("#setup-provider-copy", Static).display = bool(provider_copy)
        self._apply_provider_visibility(provider)
        # A returning user who pasted an OpenRouter key earlier setup has the
        # key pre-filled here. Treat that as "connected" too, so the revoke /
        # sign-out controls are available to remove an existing key — not just
        # after a fresh OAuth round-trip in this session.
        if provider == SETUP_PROVIDER_OPENROUTER:
            existing = self._resolve_setup_api_key(
                provider,
                self.query_one("#setup-api-key", Input).value,
            )
            if existing:
                self._openrouter_set_connected(existing)
        self.query_one("#setup-provider", Select).focus()
        if provider == SETUP_PROVIDER_OPENROUTER and self.query_one("#setup-api-key", Input).value.strip():
            self.run_worker(self._load_openrouter_models(), exclusive=False)

    @on(Button.Pressed, "#continue")
    def on_continue_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._submit_async(), exclusive=False)

    @on(Button.Pressed, "#setup-toggle-api-key")
    def on_toggle_api_key_pressed(self, event: Button.Pressed) -> None:
        api_key = self.query_one("#setup-api-key", Input)
        api_key.password = not bool(api_key.password)
        event.button.label = "🙈" if not api_key.password else "👁"

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    @on(Select.Changed, "#setup-provider")
    def on_provider_changed(self, event: Select.Changed) -> None:
        previous_provider = self._active_provider
        self._capture_provider_model_state(previous_provider)
        provider = str(event.value or "").strip() or SETUP_PROVIDER_GENERIC
        self._active_provider = provider
        context_field = self._safe_query_one("#setup-context-window", Input)
        if context_field is not None:
            context_field.value = self._provider_context_window.get(provider, "")
        base_url, api_key, _ = self._provider_defaults(provider)
        provider_copy, provider_help, model_help = self._provider_copy(provider)
        self.query_one("#setup-provider-copy", Static).update(provider_copy)
        self.query_one("#setup-provider-copy", Static).display = bool(provider_copy)
        self.query_one("#setup-base-url", Input).value = base_url
        self.query_one("#setup-base-url-help", Static).update(provider_help)
        self.query_one("#setup-api-key", Input).value = api_key
        self.query_one("#setup-model-input", Input).value = (
            self._provider_manual_model.get(provider, "")
        )
        self.query_one("#setup-model-help", Static).update(model_help)
        self.query_one("#setup-status", Static).update("")
        self.query_one("#setup-error", Static).update("")
        # Reset transient OAuth state when the user switches providers so
        # a stale headless code from a previous OpenRouter session does
        # not leak into the new one.
        self._openrouter_headless = False
        auth_code_input = self._safe_query_one(
            "#openrouter-auth-code", Input
        )
        if auth_code_input is not None:
            auth_code_input.value = ""
        self._apply_provider_visibility(provider)
        self._update_model_help_text(provider)
        if provider == SETUP_PROVIDER_OPENROUTER and api_key.strip():
            self.run_worker(self._load_openrouter_models(), exclusive=False)

    @on(Input.Submitted, "#setup-base-url")
    @on(Input.Submitted, "#setup-api-key")
    @on(Input.Submitted, "#setup-model-input")
    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.run_worker(self._submit_async(), exclusive=False)

    @on(Button.Pressed, "#setup-load-models")
    def on_load_models_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._load_openrouter_models(), exclusive=False)

    @on(Button.Pressed, "#setup-openrouter-signin")
    def on_openrouter_signin_pressed(self, _event: Button.Pressed) -> None:
        if self._validating or self._openrouter_signin_in_flight:
            return
        self._openrouter_headless = not openrouter_pkce.can_bind_localhost_callback()
        self._apply_provider_visibility(
            str(
                self.query_one("#setup-provider", Select).value
                or SETUP_PROVIDER_OPENROUTER
            )
        )
        if self._openrouter_headless:
            auth_label = self._safe_query_one(
                "#openrouter-auth-code-label", Static
            )
            if auth_label is not None:
                auth_label.update(
                    "Paste the code shown in your browser after approving the connection."
                )
        self.run_worker(
            self._openrouter_pkce_signin(headless=self._openrouter_headless),
            exclusive=True,
        )

    @on(Input.Submitted, "#openrouter-auth-code")
    def on_openrouter_auth_code_submitted(
        self, event: Input.Submitted
    ) -> None:
        if self._validating or self._openrouter_signin_in_flight:
            return
        code = str(event.value or "").strip()
        if not code:
            self._set_error("Paste the authorization code from your browser.")
            return
        self.run_worker(
            self._openrouter_pkce_signin(headless=True, pasted_code=code),
            exclusive=True,
        )

    @on(Button.Pressed, "#openrouter-manage")
    def on_openrouter_manage_pressed(self, _event: Button.Pressed) -> None:
        api_key = str(self._resolve_setup_api_key(
            SETUP_PROVIDER_OPENROUTER,
            self.query_one("#setup-api-key", Input).value,
        ) or "").strip()
        if not api_key:
            self._set_error(
                "No OpenRouter key to manage yet. Sign in or paste a key first."
            )
            return
        settings_url, _ = openrouter_pkce.openrouter_key_links(api_key=api_key)
        if openrouter_pkce.open_browser(settings_url):
            self._set_status(
                "Opened the OpenRouter page for this key. "
                "You can confirm the account and revoke the key there."
            )
        else:
            self._set_status(f"Open this page in your browser to manage the key: {settings_url}")

    @on(Button.Pressed, "#openrouter-signout")
    def on_openrouter_signout_pressed(self, _event: Button.Pressed) -> None:
        # Dismiss with a sign-out action so the app removes the key from
        # every place it is persisted (OAuth secret, config.toml api_key,
        # and the saved-provider profile that feeds the /models picker).
        # Clearing only the modal's local state would leave the saved key
        # intact and the next open would show "Connected" again.
        self.dismiss(
            {
                "action": "openrouter_signout",
                "model_name": str(self._config.model_name or "").strip(),
            }
        )

    @on(Select.Changed, "#setup-model-select")
    def on_model_select_changed(self, event: Select.Changed) -> None:
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        selected_value = str(event.value or "").strip()
        self._provider_selected_model[provider] = selected_value
        if selected_value != SETUP_MODEL_OTHER:
            self._provider_manual_model[provider] = ""
        self._apply_model_input_visibility(selected_value)
        self._update_model_help_text(provider)

    @on(Input.Changed, "#setup-model-input")
    def on_model_input_changed(self, event: Input.Changed) -> None:
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        self._provider_manual_model[provider] = event.value
        self._update_model_help_text(provider)

    @on(Input.Changed, "#setup-context-window")
    def on_context_window_changed(self, event: Input.Changed) -> None:
        if (
            self._active_provider == SETUP_PROVIDER_OLLAMA
            and not event.input.disabled
            and event.value == event.input.value
        ):
            if self._ollama_listed_selection():
                model_name = self._selected_model_name(SETUP_PROVIDER_OLLAMA)
                self._ollama_manual_context_windows[model_name] = event.value
            else:
                self._provider_context_window[SETUP_PROVIDER_OLLAMA] = event.value

    def _set_error(self, message: str) -> None:
        self.query_one("#setup-error", Static).update(message)

    def _set_status(self, message: str) -> None:
        self.query_one("#setup-status", Static).update(message)

    def _safe_query_one(self, selector: str, widget_type: type):
        """Look up a widget by id, returning ``None`` when not present.

        Some unit tests patch ``query_one`` with hand-rolled dictionaries
        that don't include every optional widget this modal owns (e.g. the
        OpenRouter sign-in button added in a later release). Treat missing
        widgets as no-ops so those tests keep passing without rewriting.
        """
        try:
            return self.query_one(selector, widget_type)
        except (NoMatches, KeyError):
            return None

    def _set_validating(self, busy: bool) -> None:
        self._validating = busy
        self.query_one("#continue", Button).disabled = busy
        self.query_one("#cancel", Button).disabled = busy
        self.query_one("#setup-provider", Select).disabled = busy
        self.query_one("#setup-base-url", Input).disabled = busy
        self.query_one("#setup-api-key", Input).disabled = busy
        self.query_one("#setup-model-select", Select).disabled = busy
        self.query_one("#setup-model-input", Input).disabled = busy
        self.query_one("#setup-toggle-api-key", Button).disabled = busy
        self.query_one("#setup-load-models", Button).disabled = busy
        context_field = self._safe_query_one("#setup-context-window", Input)
        if context_field is not None:
            context_field.disabled = busy
        signin = self._safe_query_one("#setup-openrouter-signin", Button)
        if signin is not None:
            signin.disabled = busy
        auth_code = self._safe_query_one("#openrouter-auth-code", Input)
        if auth_code is not None:
            auth_code.disabled = busy
        manage = self._safe_query_one("#openrouter-manage", Button)
        if manage is not None:
            manage.disabled = busy
        signout = self._safe_query_one("#openrouter-signout", Button)
        if signout is not None:
            signout.disabled = busy
        self._refresh_ollama_context_field(self._active_provider)

    def _ollama_listed_selection(self) -> bool:
        select = self._safe_query_one("#setup-model-select", Select)
        return select is not None and str(select.value) in RECOMMENDED_OLLAMA_MODELS

    def _refresh_ollama_context_field(self, provider: str) -> None:
        field = self._safe_query_one("#setup-context-window", Input)
        help_text = self._safe_query_one("#setup-context-window-help", Static)
        if field is None or help_text is None:
            return
        if provider != SETUP_PROVIDER_OLLAMA or not self._ollama_listed_selection():
            self._ollama_context_display_model = None
            field.disabled = self._validating
            if provider == SETUP_PROVIDER_OLLAMA:
                field.value = self._provider_context_window.get(provider, "")
            help_text.update("Enter the token limit available for this model. iTE uses it for the context meter and compaction.")
            return
        model_name = self._selected_model_name(provider)
        if self._ollama_context_display_model != model_name:
            self._ollama_context_display_model = model_name
            field.value = self._ollama_manual_context_windows.get(model_name, "")
        if model_name not in self._ollama_context_windows:
            field.value = ""
            field.disabled = True
            help_text.update("Detecting the context window from Ollama…")
            if self.is_mounted and model_name not in self._ollama_context_pending:
                self._ollama_context_pending.add(model_name)
                self.run_worker(self._load_ollama_context_window(model_name), exclusive=False)
            return
        detected = self._ollama_context_windows[model_name]
        field.disabled = self._validating or detected is not None
        if detected:
            field.value = str(detected)
            help_text.update("Context window detected from Ollama. iTE uses this limit for the context meter and compaction.")
        else:
            help_text.update("Ollama’s effective context window could not be determined. Enter the token limit available on the server.")

    async def _load_ollama_context_window(self, model_name: str) -> None:
        try:
            _error, limit = await self._probe_ollama(
                base_url=DEFAULT_BASE_URL, model_name=model_name
            )
            self._ollama_context_windows[model_name] = limit
        finally:
            self._ollama_context_pending.discard(model_name)
        if self.is_mounted and self._active_provider == SETUP_PROVIDER_OLLAMA:
            self._refresh_ollama_context_field(SETUP_PROVIDER_OLLAMA)

    def _apply_provider_visibility(self, provider: str) -> None:
        show_base_url = provider == SETUP_PROVIDER_GENERIC
        # Once signed in to OpenRouter, the API key field and the sign-in
        # controls are redundant — the key is already verified and loaded.
        signed_in_openrouter = (
            provider == SETUP_PROVIDER_OPENROUTER and self._openrouter_signed_in
        )
        show_api_key = provider != SETUP_PROVIDER_OLLAMA and not signed_in_openrouter
        show_model_select = provider == SETUP_PROVIDER_OLLAMA or (
            provider == SETUP_PROVIDER_OPENROUTER and bool(self._openrouter_models)
        )
        show_load_models = provider == SETUP_PROVIDER_OPENROUTER
        show_model_label = provider == SETUP_PROVIDER_GENERIC or show_model_select
        show_openrouter_signin = (
            provider == SETUP_PROVIDER_OPENROUTER and not self._openrouter_signed_in
        )
        show_openrouter_auth_code = (
            provider == SETUP_PROVIDER_OPENROUTER and self._openrouter_headless
        )
        show_openrouter_connected = signed_in_openrouter
        for selector, widget_type, visible in (
            ("#setup-base-url-label", Static, show_base_url),
            ("#setup-base-url", Input, show_base_url),
            ("#setup-base-url-help", Static, not signed_in_openrouter),
            ("#setup-api-key-label", Static, show_api_key),
            ("#setup-api-key-row", Horizontal, show_api_key),
            ("#setup-model-label", Static, show_model_label),
            ("#setup-model-select-row", Horizontal, show_model_select),
            ("#setup-load-models", Button, show_load_models),
            ("#setup-openrouter-signin", Button, show_openrouter_signin),
            ("#setup-openrouter-or", Static, show_openrouter_signin),
            ("#openrouter-auth-code-label", Static, show_openrouter_auth_code),
            ("#openrouter-auth-code", Input, show_openrouter_auth_code),
            ("#openrouter-connected-label", Static, show_openrouter_connected),
            ("#openrouter-actions", Horizontal, show_openrouter_connected),
            (
                "#setup-context-window-label",
                Static,
                provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC},
            ),
            (
                "#setup-context-window",
                Input,
                provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC},
            ),
            (
                "#setup-context-window-help",
                Static,
                provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC},
            ),
        ):
            widget = self._safe_query_one(selector, widget_type)
            if widget is not None:
                widget.display = visible
        if provider == SETUP_PROVIDER_OLLAMA:
            self._set_model_options(
                list(RECOMMENDED_OLLAMA_MODELS), preserve_current=True
            )
        if provider == SETUP_PROVIDER_OPENROUTER:
            self._set_model_options(self._openrouter_models, preserve_current=True)
        self.query_one("#setup-model-input", Input).display = (
            provider == SETUP_PROVIDER_GENERIC
        )
        if provider == SETUP_PROVIDER_GENERIC:
            self.query_one("#setup-model-help", Static).display = False
        elif provider == SETUP_PROVIDER_OPENROUTER and not self._openrouter_models:
            self.query_one("#setup-model-help", Static).display = False
        self._apply_model_input_visibility(
            str(self.query_one("#setup-model-select", Select).value or "").strip()
        )
        self._refresh_ollama_context_field(provider)

    def _openrouter_hide_pre_signin_controls(self) -> None:
        """Hide the API-key field and sign-in controls once connected.

        After a successful sign-in the key is already verified and stored, so
        the paste field and the "Sign in" flow are redundant. Hiding them also
        collapses the empty space they would otherwise leave in the modal.
        """
        for selector, widget_type in (
            ("#setup-provider-copy", Static),
            ("#setup-base-url-help", Static),
            ("#setup-api-key-label", Static),
            ("#setup-api-key-row", Horizontal),
            ("#setup-openrouter-signin", Button),
            ("#setup-openrouter-or", Static),
            ("#openrouter-auth-code-label", Static),
            ("#openrouter-auth-code", Input),
        ):
            widget = self._safe_query_one(selector, widget_type)
            if widget is not None:
                widget.display = False

    def _capture_provider_model_state(self, provider: str) -> None:
        context_field = self._safe_query_one("#setup-context-window", Input)
        if (
            context_field is not None
            and provider in self._provider_context_window
            and not (provider == SETUP_PROVIDER_OLLAMA and self._ollama_listed_selection())
        ):
            self._provider_context_window[provider] = context_field.value
        manual_value = self.query_one("#setup-model-input", Input).value.strip()
        if provider == SETUP_PROVIDER_GENERIC:
            self._provider_manual_model[provider] = manual_value
            self._provider_selected_model[provider] = manual_value
            return
        selected_value = str(
            self.query_one("#setup-model-select", Select).value or ""
        ).strip()
        self._provider_selected_model[provider] = selected_value
        if selected_value == SETUP_MODEL_OTHER:
            self._provider_manual_model[provider] = manual_value

    def _set_model_options(self, models: list[str], *, preserve_current: bool) -> None:
        select = self.query_one("#setup-model-select", Select)
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        current_value = (
            self._provider_selected_model.get(provider, "").strip()
            if preserve_current
            else ""
        )
        manual_input = self.query_one("#setup-model-input", Input)
        if provider == SETUP_PROVIDER_OPENROUTER:
            options = [("Select a model", SETUP_MODEL_SELECT)]
        else:
            options = []
        options.extend((model, model) for model in models)
        options.append(("Other", SETUP_MODEL_OTHER))
        select.set_options(options)

        option_values = {value for _, value in options}
        target = current_value
        if target not in option_values:
            manual_value = self._provider_manual_model.get(provider, "").strip()
            if manual_value and manual_value in option_values:
                target = manual_value
            elif current_value == SETUP_MODEL_OTHER and manual_value:
                target = SETUP_MODEL_OTHER
            if provider == SETUP_PROVIDER_OPENROUTER:
                target = SETUP_MODEL_SELECT
            elif models:
                target = models[0]
            else:
                target = SETUP_MODEL_OTHER
        select.value = target
        self._provider_selected_model[provider] = target
        if target != SETUP_MODEL_OTHER:
            manual_input.value = ""

    def _apply_model_input_visibility(self, selected_value: str) -> None:
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        model_input = self.query_one("#setup-model-input", Input)
        model_help = self.query_one("#setup-model-help", Static)
        if provider == SETUP_PROVIDER_GENERIC:
            model_input.display = True
            return
        if provider == SETUP_PROVIDER_OPENROUTER and not self._openrouter_models:
            model_input.display = False
            model_help.display = False
            return
        show_manual = selected_value == SETUP_MODEL_OTHER
        model_input.display = show_manual
        model_help.display = True
        if not show_manual:
            model_input.value = ""
            return
        model_input.value = self._provider_manual_model.get(provider, "")
        model_input.focus()

    @staticmethod
    def _ollama_api_root(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized[:-3]
        return normalized

    async def _probe_openai_compatible(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
    ) -> tuple[str | None, int | None]:
        normalized = base_url.rstrip("/")
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        timeout = httpx.Timeout(10.0, connect=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.get(f"{normalized}/models", headers=headers)
            except httpx.HTTPError as exc:
                return f"Could not reach the provider at {normalized}: {exc}", None

            if response.status_code in {401, 403}:
                return (
                    "The provider rejected this API key. Check the key and try again."
                ), None
            if response.status_code == 404:
                return (
                    "This base URL does not expose a compatible /models endpoint. "
                    "Check the provider URL and make sure it is an OpenAI-compatible API."
                ), None
            if response.status_code >= 400:
                return (
                    f"Provider check failed with status {response.status_code}. "
                    "Verify the base URL and API key."
                ), None

            try:
                payload = response.json()
            except ValueError:
                return (
                    "The provider returned invalid JSON while checking available models.",
                    None,
                )

        data = payload.get("data")
        if not isinstance(data, list):
            return None, None

        model_ids = {
            str(item.get("id") or "").strip() for item in data if isinstance(item, dict)
        }
        if model_ids and model_name not in model_ids:
            return (
                f"The model `{model_name}` is not available on this provider. "
                "Use the exact model id exposed by the provider."
            ), None
        for item in data:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != model_name:
                continue
            metadata = parse_openrouter_model_metadata(item)
            return None, metadata.context_window if metadata else None
        return None, None

    async def _fetch_openrouter_models(
        self, *, api_key: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        timeout = httpx.Timeout(10.0, connect=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                key_response = await client.get(
                    f"{OPENROUTER_BASE_URL}/key",
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                return [], f"Could not verify the OpenRouter API key: {exc}"

            if key_response.status_code in {401, 403}:
                return [], "OpenRouter rejected this API key. Check the key and try again."
            if key_response.status_code >= 400:
                return [], f"OpenRouter key check failed with status {key_response.status_code}."

            try:
                response = await client.get(
                    f"{OPENROUTER_BASE_URL}/models",
                    headers=headers,
                    params={"supported_parameters": "tools"},
                )
            except httpx.HTTPError as exc:
                return [], f"Could not load models from OpenRouter: {exc}"

        if response.status_code in {401, 403}:
            return [], "OpenRouter rejected this API key. Check the key and try again."
        if response.status_code >= 400:
            return [], f"OpenRouter model list failed with status {response.status_code}."

        try:
            payload = response.json()
        except ValueError:
            return [], "OpenRouter returned invalid JSON while listing models."

        data = payload.get("data")
        if not isinstance(data, list):
            return [], "OpenRouter did not return a model list."

        models: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            metadata = parse_openrouter_model_metadata(item)
            if (
                metadata is None
                or not _is_free_openrouter_model(item, metadata.model_name)
                or not _supports_openrouter_agentic_tools(item)
            ):
                continue
            models.append(
                {
                    "model_name": metadata.model_name,
                    "context_window": metadata.context_window,
                }
            )
        models.sort(
            key=lambda item: (
                str(item.get("model_name") or "").strip() != OPENROUTER_PREFERRED_MODEL,
                str(item.get("model_name") or ""),
            )
        )
        if not models:
            return [], "No free, tool-capable OpenRouter models were returned for this account."
        return models, None

    async def _load_openrouter_models(self) -> None:
        loaded = await self._load_openrouter_models_for_setup()
        if loaded:
            self._set_status(
                f"API key verified. Loaded {len(self._openrouter_models)} available models."
            )

    async def _openrouter_pkce_signin(
        self, *, headless: bool, pasted_code: str | None = None
    ) -> None:
        """Run the PKCE flow and populate the modal's API key input.

        On success, the key is written into ``#setup-api-key`` (so the
        existing model-load worker picks it up) and persisted to
        ``secrets.toml``. The user must still hit Continue to save the
        rest of the setup.
        """
        if self._validating or self._openrouter_signin_in_flight:
            return
        self._openrouter_signin_in_flight = True
        self._set_error("")
        key_label = f"iTE CLI ({socket.gethostname()})"
        api_key: str | None = None
        try:
            self._set_validating(True)
            if headless and not pasted_code:
                # First click on a headless system: generate a fresh
                # PKCE pair so OpenRouter accepts the code, open the
                # browser with the matching challenge, and stash the
                # verifier so the next call (from the auth-code
                # Input.Submitted handler) can complete the exchange.
                pkce = openrouter_pkce.generate_pkce_pair()
                self._pending_pkce = pkce
                self._set_status(
                    "Opening browser for OpenRouter sign-in. "
                    "Paste the authorization code here when it appears."
                )
                auth_url = openrouter_pkce.build_auth_url(
                    code_challenge=pkce.code_challenge,
                    key_label=key_label,
                    callback_url=None,
                )
                if not openrouter_pkce.open_browser(auth_url):
                    # No browser could be launched (sandboxed / headless / SSH
                    # env) — surface the URL so the user can open it manually
                    # and paste the resulting code into the field below.
                    self._set_status(
                        f"Open this URL in a browser to sign in to OpenRouter: {auth_url}"
                    )
                else:
                    self._set_status(
                        "Opening browser for OpenRouter sign-in. "
                        "Paste the authorization code here when it appears."
                    )
                return
            self._set_status(
                "Opening browser for OpenRouter sign-in…"
                if not headless
                else "Exchanging authorization code…"
            )
            if headless and pasted_code:
                pending = getattr(self, "_pending_pkce", None)
                if pending is None:
                    raise openrouter_pkce.OpenRouterAuthError(
                        "Lost the pending sign-in. Click the button again."
                    )
                api_key = openrouter_pkce.exchange_code(
                    code=pasted_code, code_verifier=pending.code_verifier
                )
            else:
                # Localhost path: run on the modal's own event loop so
                # the callback server shares it. Wrapping in
                # ``asyncio.to_thread`` and then ``asyncio.run`` inside
                # would deadlock on macOS/Python 3.11.
                api_key = await openrouter_pkce.run_localhost_pkce_flow_async(
                    key_label=key_label,
                )
        except openrouter_pkce.OpenRouterAuthError as exc:
            self._set_status("")
            self._set_error(str(exc))
            self._pending_pkce = None
            return
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self._set_status("")
            self._set_error(f"OpenRouter sign-in failed: {exc}")
            self._pending_pkce = None
            return
        finally:
            self._set_validating(False)
            self._openrouter_signin_in_flight = False
            if api_key is None and not headless:
                # No success and no error handler caught it: clear the
                # "Opening browser…" status so the modal doesn't look
                # frozen. (In normal exit paths the error or success
                # message overwrites this; this is a belt-and-braces
                # clear.)
                self._set_status("")

        try:
            save_openrouter_oauth_secret(api_key=api_key, key_label=key_label)
        except Exception as exc:  # noqa: BLE001
            # Persistence failed but the key is still usable in this session.
            # We surface the warning so the user can decide to re-run.
            self._set_error(
                f"OpenRouter verified, but the secret could not be saved: {exc}"
            )
            return
        self.query_one("#setup-api-key", Input).value = api_key
        self.query_one("#setup-api-key", Input).password = False
        self._pending_pkce = None
        # Mark the device as connected so the "View / revoke" and "Sign out"
        # row appears, giving the user visible confirmation the sign-in
        # completed and a way to revoke or forget the key. The API-key field
        # and the sign-in controls are redundant now, so hide them.
        self._openrouter_set_connected(api_key)
        self._set_status("Signed in with OpenRouter ✓. Loading available models…")
        await self._load_openrouter_models_for_setup()

    def _openrouter_set_connected(self, api_key: str) -> None:
        """Show the bold "Connected to OpenRouter" status under the provider.

        Used both after a fresh OAuth round-trip and when a returning user
        opens setup with an already-saved (e.g. pasted) OpenRouter key. Every
        pre-sign-in text/control (help lines, the API-key field, the sign-in
        button) is hidden — only the connected status and the key-management
        buttons remain.
        """
        del api_key  # kept for parity with the sign-in path / future use
        self._openrouter_signed_in = True
        connected_label = self._safe_query_one(
            "#openrouter-connected-label", Static
        )
        if connected_label is not None:
            connected_label.update("Connected to OpenRouter")
            connected_label.display = True
        actions = self._safe_query_one("#openrouter-actions", Horizontal)
        if actions is not None:
            actions.display = True
        self._openrouter_hide_pre_signin_controls()

    async def _load_openrouter_models_for_setup(self) -> bool:
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        if provider != SETUP_PROVIDER_OPENROUTER or self._validating:
            return False
        api_key = self._resolve_setup_api_key(
            provider,
            self.query_one("#setup-api-key", Input).value,
        )
        if not api_key:
            self._set_error("Enter your OpenRouter API key first.")
            return False

        self._set_error("")
        self._set_status("Verifying API key and loading available models...")
        self._set_validating(True)
        try:
            models, error = await self._fetch_openrouter_models(api_key=api_key)
        finally:
            self._set_validating(False)

        if error:
            self._set_status("")
            self._set_error(error)
            return False

        self._openrouter_models = [
            str(item.get("model_name") or "").strip()
            for item in models
            if str(item.get("model_name") or "").strip()
        ]
        self._openrouter_context_windows = {
            str(item.get("model_name") or "").strip(): int(item.get("context_window"))
            for item in models
            if str(item.get("model_name") or "").strip()
            and isinstance(item.get("context_window"), int)
            and int(item.get("context_window")) > 0
        }
        self._set_model_options(self._openrouter_models, preserve_current=True)
        self._apply_provider_visibility(provider)
        self._apply_model_input_visibility(
            str(self.query_one("#setup-model-select", Select).value or "").strip()
        )
        self._update_model_help_text(provider)
        return True

    async def _probe_ollama(
        self, *, base_url: str, model_name: str
    ) -> tuple[str | None, int | None]:
        return None, await discover_context_window(base_url, model_name)

    @staticmethod
    def _parse_context_window(value: str) -> int | None:
        value = value.strip()
        if not value or not value.isascii() or not value.isdigit():
            return None
        try:
            tokens = int(value)
        except ValueError:
            return None
        return tokens if tokens > 0 else None

    async def _validate_provider_connection(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
    ) -> tuple[str | None, int | None]:
        if provider == SETUP_PROVIDER_OLLAMA:
            if model_name in self._ollama_context_windows:
                return None, self._ollama_context_windows[model_name]
            return await self._probe_ollama(base_url=base_url, model_name=model_name)
        return await self._probe_openai_compatible(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )

    async def _submit_async(self) -> None:
        if self._validating:
            return
        provider = (
            str(self.query_one("#setup-provider", Select).value or "").strip()
            or SETUP_PROVIDER_GENERIC
        )
        base_url = self.query_one("#setup-base-url", Input).value.strip()
        api_key = self._resolve_setup_api_key(
            provider,
            self.query_one("#setup-api-key", Input).value,
        )
        selected_model = str(
            self.query_one("#setup-model-select", Select).value or ""
        ).strip()
        manual_model = self.query_one("#setup-model-input", Input).value.strip()
        if provider == SETUP_PROVIDER_GENERIC:
            model_name = manual_model
        elif selected_model == SETUP_MODEL_OTHER:
            model_name = manual_model or self._config.model_name or DEFAULT_MODEL_NAME
        elif selected_model == SETUP_MODEL_SELECT:
            model_name = ""
        else:
            model_name = (
                selected_model
                or manual_model
                or self._config.model_name
                or DEFAULT_MODEL_NAME
            )

        if provider == SETUP_PROVIDER_OLLAMA:
            # Ollama setup hides the base URL and API key inputs. Force the
            # canonical local values so stale hidden values from a previous
            # OpenRouter/custom-provider session cannot leak into the saved
            # Ollama profile.
            base_url = DEFAULT_BASE_URL
            api_key = DEFAULT_API_KEY
        if provider == SETUP_PROVIDER_OPENROUTER:
            base_url = base_url or OPENROUTER_BASE_URL

        if not base_url:
            self._set_error("Base URL is required.")
            return
        if not api_key:
            self._set_error("API key is required for the selected provider.")
            return
        if provider == SETUP_PROVIDER_OPENROUTER and not self._openrouter_models:
            loaded = await self._load_openrouter_models_for_setup()
            if loaded:
                self._set_status("API key verified. Choose a model to continue.")
            return
        if not model_name:
            self._set_error("Model name is required.")
            return

        configured_context_window = None
        listed_ollama = provider == SETUP_PROVIDER_OLLAMA and self._ollama_listed_selection()
        if listed_ollama and model_name not in self._ollama_context_windows:
            self._set_validating(True)
            try:
                await self._load_ollama_context_window(model_name)
            finally:
                self._set_validating(False)
        ollama_detected = (
            self._ollama_context_windows.get(model_name) if listed_ollama else None
        )
        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}:
            configured_context_window = ollama_detected or self._parse_context_window(
                self.query_one("#setup-context-window", Input).value
            )
            if configured_context_window is None:
                self._set_error(
                    "Context window is required. Enter a positive whole number of tokens, for example 1000000."
                )
                self.query_one("#setup-context-window", Input).focus()
                return

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._set_error("Base URL must be a valid http/https URL.")
            return

        self._set_error("")
        self._set_status("Checking provider connection...")
        self._set_validating(True)
        try:
            error, detected_context_window = await self._validate_provider_connection(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
            )
        finally:
            self._set_validating(False)

        if error:
            self._set_status("")
            self._set_error(error)
            return

        self._set_status("Provider verified.")

        self.dismiss(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model_name": model_name,
                "context_window": (
                    self._openrouter_context_windows.get(model_name)
                    if provider == SETUP_PROVIDER_OPENROUTER
                    and detected_context_window is None
                    else (
                        configured_context_window
                        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}
                        else (
                            detected_context_window
                            if detected_context_window is not None
                            and detected_context_window > 0
                            else int(
                                self._config.model.context_window
                                or DEFAULT_CONTEXT_WINDOW
                            )
                        )
                    )
                ),
                "context_window_source": (
                    "openrouter_models_api"
                    if provider == SETUP_PROVIDER_OPENROUTER
                    and model_name in self._openrouter_context_windows
                    else (
                        ("ollama_model_api" if ollama_detected else "user_configured")
                        if provider in {SETUP_PROVIDER_OLLAMA, SETUP_PROVIDER_GENERIC}
                        else (
                            "fallback_default"
                            if provider == SETUP_PROVIDER_OPENROUTER
                            else (
                                str(
                                    getattr(
                                        self._config.model, "context_window_source", ""
                                    )
                                    or ""
                                ).strip()
                                or "fallback_default"
                            )
                        )
                    )
                ),
                "approval": self._config.approval.value,
            }
        )
