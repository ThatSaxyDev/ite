"""Tool for recording evidence-backed Goal mode outcomes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class GoalOutcomeParams(BaseModel):
    action: Literal["record_evidence", "complete", "report_blocked"] = Field(
        ..., description="Goal outcome to record"
    )
    summary: str = Field(..., min_length=1, description="Concise outcome summary")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Concrete verification references for evidence or completion",
    )


class GoalOutcomeTool(Tool):
    name = "goal_outcome"
    description = (
        "Record evidence, report a blocker, or complete the active goal. "
        "Completion requires concrete evidence references."
    )
    kind = ToolKind.MEMORY
    schema = GoalOutcomeParams

    def __init__(self, config) -> None:
        super().__init__(config)
        self._session: Any | None = None

    def set_session(self, session: Any | None) -> None:
        self._session = session

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GoalOutcomeParams(**invocation.params)
        session = self._session
        if session is None or session.goal_state is None:
            return ToolResult.error_result("No active goal exists for this thread.")

        if params.action == "record_evidence":
            session.record_goal_evidence(params.summary, evidence=params.evidence)
            return ToolResult.success_result(
                "Goal evidence recorded.", metadata={"action": params.action}
            )
        if params.action == "report_blocked":
            session.block_goal(params.summary)
            return ToolResult.success_result(
                "Goal marked as blocked.", metadata={"action": params.action}
            )
        if not params.evidence:
            return ToolResult.error_result(
                "Completion requires at least one concrete evidence reference.",
                metadata={"action": params.action},
            )
        session.complete_goal(params.summary, evidence=params.evidence)
        return ToolResult.success_result(
            "Goal completed with recorded evidence.",
            metadata={"action": params.action},
        )
