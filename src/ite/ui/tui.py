"""Stub TUI module - functionality moved to Reup UI.

This module exists for backward compatibility with code that imports it,
but all functionality is now handled by src/ite/ui/reup/.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from ite.config.config import Config
    from ite.tools.base import ToolConfirmation


def get_console() -> Console:
    """Return a no-op console for backward compatibility."""
    return Console()


class TUI:
    """Stub TUI class - all functionality moved to Reup UI."""

    def __init__(self, config: Config, console: Console | None = None) -> None:
        self.config = config

    def start_spinner(self, command: str = "", message: str = "Thinking") -> None:
        pass

    def stop_spinner(self) -> None:
        pass

    def begin_assistant(self) -> None:
        pass

    def end_assistant(self, final_content: str | None = None) -> None:
        pass

    def render_change_summary(self, change_set: Any | None, cwd: Path) -> None:
        pass

    def stream_assistant_delta(self, content: str) -> None:
        pass

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        pass

    def print_welcome(
        self,
        model: str = "",
        cwd: str = "",
        commands: list[str] | None = None,
        version: str = "",
    ) -> None:
        pass

    def tool_call_complete(
        self,
        call_id: str,
        success: bool,
        result: str,
        error: str | None,
    ) -> None:
        pass

    def handle_confirmation(self, confirmation: ToolConfirmation) -> bool:
        return True

    def recoverable_sandbox_note(self, tool_name: str, error: str) -> None:
        pass

    def prompt_plan_question(
        self,
        question: str,
        options: list[str],
        recommended_index: int | None = None,
    ) -> int:
        return 0

    def prompt_plan_implementation(self, asked_questions: int = 0) -> bool:
        return True