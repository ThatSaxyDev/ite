from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class ReupTUIAdapter:
    """Adapter that wraps ReupApp to provide TUI-like interface."""

    def __init__(self, app: "ReupApp") -> None:
        self._app = app
        # Track spinner state locally to avoid race conditions with async workers
        self._spinner_handle: str | None = None
        self._spinner_lines: list[str] = []
        self._spinner_started: bool = False

    @property
    def cwd(self) -> Path:
        return self._app.config.cwd

    @cwd.setter
    def cwd(self, value: Path) -> None:
        self._app.config.cwd = Path(value)
        self._app.refresh_header()

    def print_welcome(
        self,
        model: str = "",
        cwd: str = "",
        commands: list[str] | None = None,
        version: str = "",
    ) -> None:
        from ite.update_check import current_runtime_version

        version = version or current_runtime_version()
        cwd_name = os.path.basename(cwd) or cwd
        msg = f"iTE ready\nModel: {model or 'not set'}\nWorkspace: {cwd_name}\nVersion: {version}"
        if commands:
            msg += "\nCommands: " + ", ".join(commands)
        self._app.post_system("Welcome", msg)

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        self._app.run_worker(
            self._app.add_tool_call_start(
                call_id=call_id,
                name=name,
                tool_kind=tool_kind,
                arguments=arguments,
            ),
            exclusive=False,
        )

    def tool_call_complete(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        truncated: bool,
        exit_code: int | None,
    ) -> None:
        self._app.run_worker(
            self._app.update_tool_call(
                call_id=call_id,
                name=name,
                tool_kind=tool_kind,
                success=success,
                output=output,
                error=error,
                metadata=metadata,
                diff=diff,
                truncated=truncated,
                exit_code=exit_code,
            ),
            exclusive=False,
        )

    async def _start_new_thread(self) -> None:
        await self._app.start_new_thread()

    async def _close_current_thread(self) -> None:
        await self._app.close_current_thread()

    async def _open_settings_screen(self) -> None:
        await self._app._open_settings_screen()

    def start_spinner(self, command: str, message: str = "Thinking") -> None:
        """Show streaming command card like /mcp start - fixed title with spinner."""
        self._spinner_handle = command  # Use command as handle (/init, /mcp, etc.)
        self._spinner_lines = []
        # Create card with message as pending_text - this displays with spinner
        # but isn't a persistent line, so it can be replaced
        self._app.run_worker(
            self._app.start_streaming_command_result(command, pending_text=message),
            exclusive=False,
        )

    async def begin_command_progress(self, command: str, message: str) -> None:
        """Mount before updates so fast commands cannot leave an orphan spinner."""
        await self._app.start_streaming_command_result(command, pending_text=message)

    async def update_command_progress(self, command: str, message: str) -> None:
        await self._app._update_streaming_command_pending(command, message)

    async def finish_command_progress(
        self, command: str, message: str, *, status: str
    ) -> None:
        """Replace live activity with one compact, theme-aware durable result."""
        await self._app._update_streaming_command_pending(command, None)
        await self._app._append_command_result_card(command, message)
        existing = self._app._streaming_command_cards.get(command)
        if existing is not None and status == "failed":
            existing[0].add_class("command-error")
        self._app.finalize_streaming_command_result(command)

    def change_spinner(self, message: str) -> None:
        """Update spinner status - replaces current line with new status (like tool calls)."""
        if not self._spinner_handle:
            return
        # Update pending text and clear lines so spinner shows with new message
        self._app.start_streaming_command_result_update_pending(
            self._spinner_handle, message
        )

    def step_spinner(self, message: str) -> None:
        """Commit current step as completed line, start new pending step with spinner.

        Unlike change_spinner() which replaces the current line, step_spinner()
        appends the current pending message as a completed line and starts a
        new pending step. This creates a progress trail like subagents show.
        """
        if not self._spinner_handle:
            # No active spinner, just start one
            self.start_spinner(self._spinner_handle or "/init", message)
            return
        # Commit current pending as a line, start new pending
        self._app.run_worker(
            self._app._commit_and_update_streaming_pending(
                self._spinner_handle, message
            ),
            exclusive=False,
        )

    def stream_content(self, chunk: str) -> None:
        """Stream content into the card body (like LLM token streaming).

        This appends text incrementally to show live generation progress.
        """
        if not self._spinner_handle:
            return
        self._app.run_worker(
            self._app._append_streaming_content(self._spinner_handle, chunk),
            exclusive=False,
        )

    def stop_spinner(self) -> None:
        """Finalize spinner card."""
        if self._spinner_handle:
            self._app.finalize_streaming_command_result(self._spinner_handle)
            self._spinner_handle = None
            self._spinner_lines = []

    def append_line(self, command: str, message: str) -> None:
        """Append a completed line to a streaming command card."""
        self._app.run_worker(
            self._app._append_command_result_card(command, message),
            exclusive=False,
        )

    def post_success_card(self, title: str, message: str, details: str = "") -> None:
        """Post a professional success notification card."""
        from rich.text import Text

        body = Text()
        body.append(message, style=self._app._style("success"))
        if details:
            body.append("\n", style=self._app._style("muted"))
            body.append(details, style=self._app._style("muted"))

        self._app.run_worker(
            self._app.add_assistant_card(title, body, css_class="system"),
            exclusive=False,
        )
