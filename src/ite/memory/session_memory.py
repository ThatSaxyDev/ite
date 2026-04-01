from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ite.config.loader import get_data_dir

if TYPE_CHECKING:
    from ite.agent.session import Session


def _normalize_text(value: str | None) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _truncate(value: str | None, limit: int = 280) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


class SessionMemoryManager:
    """Persist a structured working-memory artifact for the current session."""

    def __init__(self, cwd: str | Path, *, session_id: str) -> None:
        self.cwd = Path(cwd).resolve()
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def _workspace_fallback_root(self) -> Path:
        return self.cwd / ".ite" / "session_memory"

    def _ensure_dir(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        return root

    def _root(self) -> Path:
        try:
            return self._ensure_dir(get_data_dir() / "session_memory")
        except OSError:
            return self._ensure_dir(self._workspace_fallback_root())

    def path(self) -> Path:
        return self._root() / f"{self._session_id}.md"

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            os.chmod(path, 0o600)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def get_content(self) -> str | None:
        target = self.path()
        if not target.exists():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            return None

    def refresh_from_session(self, session: Session) -> Path:
        content = self._render_session_memory(session)
        target = self.path()
        self._atomic_write_text(target, content)
        return target

    def _render_session_memory(self, session: Session) -> str:
        title = _truncate(session.name or self._derive_title(session), 80) or "Untitled session"
        current_state = _truncate(session._derive_current_focus(), 400)
        task_spec = _truncate(self._first_user_message(session), 700)
        files_section = self._render_files_section(session)
        workflow = self._render_workflow_section(session)
        errors = self._render_errors_section(session)
        worklog = self._render_worklog(session)
        pending_steps = self._render_pending_steps(session)
        plan_text = _truncate(session.current_plan_text(), 700)

        sections = [
            "# Session Title",
            title,
            "",
            "# Current State",
            current_state or "No active state captured yet.",
            "",
            "# Task Specification",
            task_spec or "No task specification captured yet.",
            "",
            "# Plan",
            plan_text or "No active plan.",
            "",
            "# Pending Steps",
            pending_steps or "No pending steps captured.",
            "",
            "# Files and Functions",
            files_section or "No file activity captured yet.",
            "",
            "# Workflow",
            workflow or "No workflow captured yet.",
            "",
            "# Errors and Corrections",
            errors or "No errors captured yet.",
            "",
            "# Worklog",
            worklog or "No worklog captured yet.",
            "",
        ]
        return "\n".join(sections).strip() + "\n"

    def _derive_title(self, session: Session) -> str:
        first_user = self._first_user_message(session)
        if not first_user:
            return "Untitled session"
        return first_user.splitlines()[0].strip()

    def _first_user_message(self, session: Session) -> str:
        if not session.context_manager:
            return ""
        for msg in session.context_manager.get_messages():
            if msg.get("role") == "user":
                content = str(msg.get("content", "") or "").strip()
                if content:
                    return content
        return ""

    def _recent_snapshot_messages(self, session: Session) -> list[dict[str, Any]]:
        if not session.context_manager:
            return []
        return session.context_manager.get_snapshot_messages()[-24:]

    def _render_files_section(self, session: Session) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for msg in reversed(self._recent_snapshot_messages(session)):
            tool_ui = msg.get("tool_ui")
            if not isinstance(tool_ui, dict):
                continue
            metadata = tool_ui.get("metadata")
            if not isinstance(metadata, dict):
                continue
            candidate_paths = [
                metadata.get("path"),
                metadata.get("file_path"),
                metadata.get("target_path"),
            ]
            for raw_path in candidate_paths:
                path = _normalize_text(str(raw_path or ""))
                if not path or path in seen:
                    continue
                seen.add(path)
                lines.append(f"- {path}")
                if len(lines) >= 8:
                    return "\n".join(lines)
        return "\n".join(lines)

    def _render_workflow_section(self, session: Session) -> str:
        lines: list[str] = []
        for msg in reversed(self._recent_snapshot_messages(session)):
            if msg.get("role") != "assistant":
                continue
            for tool_call in reversed(list(msg.get("tool_calls") or [])):
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                if function.get("name") != "shell":
                    continue
                arguments = function.get("arguments")
                if not isinstance(arguments, str):
                    continue
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
                command = _truncate(str(parsed.get("command", "") or ""), 180)
                if command:
                    lines.append(f"- {command}")
                if len(lines) >= 6:
                    return "\n".join(reversed(lines))
        return "\n".join(reversed(lines))

    def _render_errors_section(self, session: Session) -> str:
        lines: list[str] = []
        issues = list(getattr(session.runtime_status, "issues", []) or [])
        for issue in issues[-4:]:
            message = _truncate(getattr(issue, "message", ""), 200)
            details = _truncate(getattr(issue, "details", ""), 200)
            if message:
                lines.append(f"- {message}")
                if details:
                    lines.append(f"  Details: {details}")

        for msg in reversed(self._recent_snapshot_messages(session)):
            tool_ui = msg.get("tool_ui")
            if not isinstance(tool_ui, dict):
                continue
            if bool(tool_ui.get("success", True)):
                continue
            name = _normalize_text(str(tool_ui.get("name", "") or "")) or "tool"
            error = _truncate(str(tool_ui.get("error") or tool_ui.get("output") or ""), 220)
            if error:
                lines.append(f"- {name}: {error}")
            if len(lines) >= 6:
                break
        return "\n".join(lines)

    def _render_pending_steps(self, session: Session) -> str:
        state = session.export_todos_state()
        execution = state.get("execution", []) if isinstance(state, dict) else []
        lines: list[str] = []
        if isinstance(execution, list):
            for item in execution:
                if not isinstance(item, dict):
                    continue
                if bool(item.get("completed", False)):
                    continue
                content = _truncate(str(item.get("content", "") or ""), 180)
                if content:
                    lines.append(f"- {content}")
                if len(lines) >= 6:
                    break
        return "\n".join(lines)

    def _render_worklog(self, session: Session) -> str:
        lines: list[str] = []
        for msg in self._recent_snapshot_messages(session)[-12:]:
            role = str(msg.get("role", "") or "").strip()
            content = _truncate(str(msg.get("content", "") or ""), 180)
            if role not in {"user", "assistant"} or not content:
                continue
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)
