from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ite.safety.approval import is_safe_command
from ite.tools.base import ToolMetadata


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    redirect_to: str | None = None


class ToolSelectionPolicy:
    """Deterministic eligibility checks for model-selected tool calls."""

    def evaluate(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
        metadata: ToolMetadata,
        plan_mode_enabled: bool,
        plan_phase: str,
        todo_execution_handoff_active: bool = False,
    ) -> PolicyDecision:
        in_planing_phase = plan_mode_enabled and plan_phase != "executing"
        if in_planing_phase and not metadata.allowed_in_plan_mode:
            if tool_name == "shell":
                command = str(params.get("command", "")).strip()
                if command and is_safe_command(command):
                    return PolicyDecision(allowed=True)
            return PolicyDecision(
                allowed=False,
                reason=(
                    "Tool blocked by policy during planning phase. "
                    "Use read/search tools first and execute mutating steps after approval."
                ),
            )

        if tool_name == "todos" and in_planing_phase:
            scope = str(params.get("scope", "planning")).strip().lower() or "planning"
            if scope == "execution" and not todo_execution_handoff_active:
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Execution todos are blocked during planning phase. "
                        "Use scope='planning' until plan execution handoff is active."
                    ),
                )

        if tool_name.startswith("subagent_"):
            goal = str(params.get("goal", "")).strip()
            if self._looks_like_simple_lookup(goal):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Subagent blocked for simple lookup. "
                        "Use direct tools (`grep`, `glob`, `read_file`, `list_dir`) first."
                    ),
                    redirect_to="grep",
                )

        if tool_name == "read_file":
            path = str(
                params.get("path")
                or params.get("file")
                or params.get("file_path")
                or params.get("filepath")
                or params.get("target")
                or ""
            ).strip().lower()
            offset = params.get("offset")
            limit = params.get("limit")
            if path.endswith(".json") and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured JSON inspection should use `read_json` instead of `read_file` "
                        "unless exact file text or line-based reading is required."
                    ),
                    redirect_to="read_json",
                )
            if path.endswith(".toml") and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured TOML inspection should use `read_toml` instead of `read_file` "
                        "unless exact file text or line-based reading is required."
                    ),
                    redirect_to="read_toml",
                )
            if path.endswith((".yaml", ".yml")) and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured YAML inspection should use `read_yaml` instead of `read_file` "
                        "unless exact file text or line-based reading is required."
                    ),
                    redirect_to="read_yaml",
                )
            if path.endswith(".env") and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured environment inspection should use `read_env` instead of `read_file` "
                        "unless exact file text or line-based reading is required."
                    ),
                    redirect_to="read_env",
                )
            if path.endswith(".pdf") and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "PDF inspection should use `read_pdf` instead of `read_file` "
                        "unless exact raw bytes or line-based text output is required."
                    ),
                    redirect_to="read_pdf",
                )
            if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) and offset in (None, "", 1) and limit in (None, ""):
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Image inspection should use `read_image` instead of `read_file` "
                        "unless exact raw bytes are required."
                    ),
                    redirect_to="read_image",
                )

        if tool_name == "edit":
            path = str(
                params.get("path")
                or params.get("file")
                or params.get("file_path")
                or params.get("filepath")
                or params.get("target")
                or ""
            ).strip().lower()
            old_string = str(params.get("old_string") or params.get("old") or "").strip()
            if path.endswith(".json") and old_string:
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured JSON updates should use `edit_json` instead of `edit` "
                        "unless exact raw text replacement is required."
                    ),
                    redirect_to="edit_json",
                )
            if path.endswith(".toml") and old_string:
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured TOML updates should use `write_toml` instead of `edit` "
                        "unless exact raw text replacement is required."
                    ),
                    redirect_to="write_toml",
                )
            if path.endswith((".yaml", ".yml")) and old_string:
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured YAML updates should use `write_yaml` instead of `edit` "
                        "unless exact raw text replacement is required."
                    ),
                    redirect_to="write_yaml",
                )
            if path.endswith(".env") and old_string:
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        "Structured environment updates should use `write_env` instead of `edit` "
                        "unless exact raw text replacement is required."
                    ),
                    redirect_to="write_env",
                )

        return PolicyDecision(allowed=True)

    def _looks_like_simple_lookup(self, goal: str) -> bool:
        if not goal:
            return False

        short_goal = len(goal) <= 140
        lookup_terms = (
            "find",
            "where",
            "which file",
            "locate",
            "show me",
            "what line",
            "path to",
            "search for",
        )
        has_lookup_term = any(term in goal.lower() for term in lookup_terms)
        broad_terms = (
            "review",
            "audit",
            "architecture",
            "refactor",
            "system-wide",
            "across the codebase",
            "comprehensive",
        )
        has_broad_term = any(term in goal.lower() for term in broad_terms)
        return short_goal and has_lookup_term and not has_broad_term
