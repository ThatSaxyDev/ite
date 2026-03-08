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
