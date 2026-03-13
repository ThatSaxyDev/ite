from __future__ import annotations
from typing import Any
from datetime import datetime
from dataclasses import dataclass
import os
import logging
from ite.config.loader import get_data_dir
import json
from pathlib import Path
from uuid import uuid4
from ite.client.response import TokenUsage

logger = logging.getLogger(__name__)

SNAPSHOT_KEEP_FULL_TOOL_RESULTS = 12
SNAPSHOT_KEEP_FULL_TOOL_CALL_ASSISTANT_MESSAGES = 12
SNAPSHOT_MAX_OLD_TOOL_RESULT_CHARS = 480
SNAPSHOT_MAX_OLD_TOOL_ARG_CHARS = 320
SNAPSHOT_MAX_MESSAGE_CHARS = 12000

REQUIRED_SESSION_FIELDS = (
    "session_id",
    "created_at",
    "updated_at",
    "turn_count",
)


def _truncate_text(value: Any, max_chars: int, suffix: str) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + suffix


def _compact_messages_for_snapshot(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return []

    preserved_tool_result_indexes: set[int] = set()
    preserved_tool_call_indexes: set[int] = set()

    tool_results_kept = 0
    assistant_tool_calls_kept = 0

    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        role = msg.get("role")
        if role == "tool" and tool_results_kept < SNAPSHOT_KEEP_FULL_TOOL_RESULTS:
            preserved_tool_result_indexes.add(index)
            tool_results_kept += 1
        elif (
            role == "assistant"
            and msg.get("tool_calls")
            and assistant_tool_calls_kept < SNAPSHOT_KEEP_FULL_TOOL_CALL_ASSISTANT_MESSAGES
        ):
            preserved_tool_call_indexes.add(index)
            assistant_tool_calls_kept += 1

    compacted: list[dict[str, Any]] = []
    for index, msg in enumerate(messages):
        entry = dict(msg)
        role = entry.get("role")
        content = entry.get("content", "")

        if isinstance(content, str) and len(content) > SNAPSHOT_MAX_MESSAGE_CHARS:
            entry["content"] = _truncate_text(
                content,
                SNAPSHOT_MAX_MESSAGE_CHARS,
                "\n\n...[saved session content truncated]",
            )

        if role == "tool" and index not in preserved_tool_result_indexes:
            original = str(entry.get("content", "") or "")
            entry["content"] = _truncate_text(
                original,
                SNAPSHOT_MAX_OLD_TOOL_RESULT_CHARS,
                "\n...[older tool output trimmed in saved session]",
            )

        if (
            role == "assistant"
            and entry.get("tool_calls")
            and index not in preserved_tool_call_indexes
        ):
            compacted_tool_calls: list[dict[str, Any]] = []
            for tool_call in entry.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_copy = dict(tool_call)
                function = dict(tool_call_copy.get("function") or {})
                arguments = function.get("arguments", "")
                if isinstance(arguments, str):
                    function["arguments"] = _truncate_text(
                        arguments,
                        SNAPSHOT_MAX_OLD_TOOL_ARG_CHARS,
                        "...",
                    )
                tool_call_copy["function"] = function
                compacted_tool_calls.append(tool_call_copy)
            entry["tool_calls"] = compacted_tool_calls

        compacted.append(entry)

    return compacted


@dataclass
class SessionSnapshot:
    session_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    messages: list[dict[str, Any]]
    total_usage: TokenUsage
    name: str | None = None
    workspace_path: str | None = None
    plan_mode_enabled: bool = False
    plan_phase: str = "idle"
    plan_questions_asked: int = 0
    plan_target_questions: int = 3
    pending_plan_text: str | None = None
    active_plan_text: str | None = None
    todos_state: dict[str, Any] | None = None
    show_planning_todos: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "workspace_path": self.workspace_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "turn_count": self.turn_count,
            "messages": _compact_messages_for_snapshot(self.messages),
            "total_usage": self.total_usage.__dict__,
            "plan_mode_enabled": self.plan_mode_enabled,
            "plan_phase": self.plan_phase,
            "plan_questions_asked": self.plan_questions_asked,
            "plan_target_questions": self.plan_target_questions,
            "pending_plan_text": self.pending_plan_text,
            "active_plan_text": self.active_plan_text,
            "todos_state": self.todos_state,
            "show_planning_todos": self.show_planning_todos,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionSnapshot":
        return cls(
            session_id=data["session_id"],
            name=data.get("name"),
            workspace_path=data.get("workspace_path"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            turn_count=data["turn_count"],
            messages=data["messages"],
            total_usage=TokenUsage(**data["total_usage"]),
            plan_mode_enabled=bool(data.get("plan_mode_enabled", False)),
            plan_phase=str(data.get("plan_phase", "idle")),
            plan_questions_asked=int(data.get("plan_questions_asked", 0)),
            plan_target_questions=int(data.get("plan_target_questions", 3)),
            pending_plan_text=data.get("pending_plan_text"),
            active_plan_text=data.get("active_plan_text"),
            todos_state=data.get("todos_state"),
            show_planning_todos=bool(data.get("show_planning_todos", False)),
        )


class SessionManager:
    def __init__(self):
        self.data_dir = get_data_dir()
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir = self.data_dir / "checkpoints"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.sessions_dir, 0o700)
        os.chmod(self.checkpoints_dir, 0o700)

    def _atomic_write_json(self, file_path: Path, data: dict[str, Any]) -> None:
        tmp_path = file_path.with_name(
            f".{file_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, file_path)
            os.chmod(file_path, 0o600)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _quarantine_session_file(self, file_path: Path, reason: str) -> None:
        corrupt_dir = self.sessions_dir / "corrupt"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(corrupt_dir, 0o700)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine_path = corrupt_dir / f"{file_path.stem}.{timestamp}.json"

        try:
            os.replace(file_path, quarantine_path)
            os.chmod(quarantine_path, 0o600)
            logger.warning(
                "Quarantined corrupt session file %s to %s: %s",
                file_path,
                quarantine_path,
                reason,
            )
        except OSError as e:
            logger.warning(
                "Failed to quarantine corrupt session file %s: %s",
                file_path,
                e,
            )

    def _load_session_json(
        self,
        file_path: Path,
        *,
        quarantine_on_error: bool = True,
    ) -> dict[str, Any] | None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            if quarantine_on_error:
                self._quarantine_session_file(file_path, str(e))
            return None

        if not isinstance(data, dict):
            if quarantine_on_error:
                self._quarantine_session_file(file_path, "JSON root must be an object")
            return None

        missing_fields = [field for field in REQUIRED_SESSION_FIELDS if field not in data]
        if missing_fields:
            if quarantine_on_error:
                self._quarantine_session_file(
                    file_path,
                    f"Missing required fields: {', '.join(missing_fields)}",
                )
            return None

        return data

    def save_session(self, snapShot: SessionSnapshot) -> None:
        file_path = self.sessions_dir / f"{snapShot.session_id}.json"
        self._atomic_write_json(file_path, snapShot.to_dict())

    def list_sessions(
        self,
        *,
        workspace_path: str | Path | None = None,
        include_legacy_unscoped: bool = True,
    ) -> list[dict[str, Any]]:
        target_workspace = (
            str(Path(workspace_path).resolve()) if workspace_path is not None else None
        )
        sessions = []
        for file_path in self.sessions_dir.glob("*.json"):
            data = self._load_session_json(file_path)
            if not data:
                continue

            stored_workspace = data.get("workspace_path")
            if target_workspace is not None:
                if stored_workspace:
                    if str(Path(stored_workspace).resolve()) != target_workspace:
                        continue
                elif not include_legacy_unscoped:
                    continue

            sessions.append(
                {
                    "session_id": data["session_id"],
                    "name": data.get("name"),
                    "workspace_path": stored_workspace,
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "turn_count": data["turn_count"],
                }
            )

        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    def list_workspaces(self) -> list[str]:
        workspaces: set[str] = set()
        for file_path in self.sessions_dir.glob("*.json"):
            data = self._load_session_json(file_path)
            if not data:
                continue
            workspace = data.get("workspace_path")
            if workspace:
                workspaces.add(str(Path(workspace).resolve()))
        return sorted(workspaces)

    def load_session(self, session_id: str) -> SessionSnapshot | None:
        file_path = self.sessions_dir / f"{session_id}.json"

        if not file_path.exists():
            return None

        data = self._load_session_json(file_path)
        if not data:
            return None

        return SessionSnapshot.from_dict(data)

    def save_checkpoint(self, snapshot: SessionSnapshot) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_id = f"{snapshot.session_id}_{timestamp}"
        file_path = self.checkpoints_dir / f"{checkpoint_id}.json"
        self._atomic_write_json(file_path, snapshot.to_dict())
        return checkpoint_id

    def load_checkpoint(self, checkpoint_id: str) -> SessionSnapshot | None:
        file_path = self.checkpoints_dir / f"{checkpoint_id}.json"

        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        return SessionSnapshot.from_dict(data)

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for a given session ID."""
        checkpoints = []
        for file_path in self.checkpoints_dir.glob(f"{session_id}_*.json"):
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            # Extract timestamp from the checkpoint filename
            checkpoint_id = file_path.stem
            checkpoints.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "created_at": data.get("updated_at", data.get("created_at", "")),
                    "turn_count": data.get("turn_count", 0),
                }
            )

        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)
        return checkpoints
