from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ite.agent.events import AgentEvent

REMOTE_PROTOCOL_VERSION = 1
MAX_REMOTE_TRANSCRIPT_MESSAGES = 80
MAX_REMOTE_TEXT_CHARS = 2400

_REMOTE_SUPPRESSED_TOOL_ERRORS: dict[str, set[str]] = {
    "shell": {"Parameter 'command': Field required"},
    "read_file": {"Parameter 'path': Field required"},
    "read_json": {"Parameter 'path': Field required"},
    "read_toml": {"Parameter 'path': Field required"},
    "read_yaml": {"Parameter 'path': Field required"},
    "read_env": {"Parameter 'path': Field required"},
    "read_pdf": {"Parameter 'path': Field required"},
    "read_image": {"Parameter 'path': Field required"},
    "grep": {"Parameter 'pattern': Field required"},
    "write_file": {
        "Parameter 'path': Field required",
        "Parameter 'content': Field required",
        "Parameter 'path': Field required; Parameter 'content': Field required",
    },
    "edit": {
        "Parameter 'path': Field required",
        "Parameter 'new_string': Field required",
        "Parameter 'path': Field required; Parameter 'new_string': Field required",
    },
    "apply_patch": {"Parameter 'patch': Field required"},
    "memory": {"Parameter 'action': Field required"},
    "skills": {
        "Parameter '': Value error, skill is required for show, activate, and deactivate"
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_iso_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.astimezone().astimezone(timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def compact_text(value: Any, limit: int = MAX_REMOTE_TEXT_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def _normalize_validation_error(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("Error: "):
        text = text.removeprefix("Error: ").strip()
    if not text.startswith("Invalid parameters: "):
        return ""
    detail = text.removeprefix("Invalid parameters: ").strip()
    detail = detail.split("\n\nOutput:", 1)[0].strip()
    detail = detail.split("\nOutput:", 1)[0].strip()
    return detail


def _is_suppressible_tool_failure(
    tool_name: Any,
    error_text: Any,
    metadata: Any = None,
) -> bool:
    normalized_name = str(tool_name or "").strip()
    if not normalized_name:
        return False
    if isinstance(metadata, dict) and bool(metadata.get("suppressed")):
        return True
    detail = _normalize_validation_error(error_text)
    if not detail:
        return False
    return detail in _REMOTE_SUPPRESSED_TOOL_ERRORS.get(normalized_name, set())


def serialize_transcript_message(event: dict[str, Any]) -> dict[str, Any] | None:
    message = event.get("message") if isinstance(event, dict) else None
    if not isinstance(message, dict):
        return None
    role = str(message.get("role") or "").strip()
    if not role or role == "system":
        return None

    payload: dict[str, Any] = {
        "role": role,
        "created_at": normalize_iso_timestamp(event.get("created_at")),
    }

    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        payload["content"] = compact_text(content)

    if role == "assistant":
        tool_calls = []
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            tool_calls.append(
                {
                    "id": str(tool_call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": compact_text(function.get("arguments") or "", 800),
                }
            )
        if tool_calls:
            payload["tool_calls"] = tool_calls

    if role == "tool":
        tool_ui = message.get("tool_ui") if isinstance(message.get("tool_ui"), dict) else {}
        tool_name = str(tool_ui.get("name") or message.get("name") or "").strip()
        metadata = tool_ui.get("metadata") if isinstance(tool_ui.get("metadata"), dict) else None
        error_text = tool_ui.get("error")
        if error_text is None:
            error_text = tool_ui.get("output")
        if error_text is None:
            error_text = message.get("content", "")
        if _is_suppressible_tool_failure(tool_name, error_text, metadata):
            return None
        payload["tool_call_id"] = str(message.get("tool_call_id") or "")
        payload["name"] = tool_name

    return payload


def build_remote_transcript(
    events: list[dict[str, Any]],
    *,
    max_messages: int = MAX_REMOTE_TRANSCRIPT_MESSAGES,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for event in events[-max_messages:]:
        entry = serialize_transcript_message(event)
        if entry is not None:
            serialized.append(entry)
    return serialized


def serialize_agent_event(
    event: AgentEvent,
    *,
    session_id: str,
    turn_id: int,
) -> dict[str, Any]:
    return {
        "protocol_version": REMOTE_PROTOCOL_VERSION,
        "session_id": session_id,
        "turn_id": turn_id,
        "timestamp": utc_now_iso(),
        "event": {
            "type": event.type.value,
            "data": json_safe(event.data),
        },
    }


def serialize_approval_request(
    *,
    request_id: str,
    tool_name: str,
    description: str,
    command: str | None,
    diff: str | None,
    session_id: str,
) -> dict[str, Any]:
    return {
        "protocol_version": REMOTE_PROTOCOL_VERSION,
        "request_id": request_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "description": compact_text(description, 6000),
        "command": compact_text(command or "", 2000) or None,
        "diff": compact_text(diff or "", 12000) or None,
        "timestamp": utc_now_iso(),
    }
