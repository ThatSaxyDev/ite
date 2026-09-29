"""Tool for recording evidence-backed Goal mode outcomes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from ite.tools.builtin.goal_progress import GoalProofInput


class GoalOutcomeParams(BaseModel):
    action: Literal["record_evidence", "complete", "report_blocked"] = Field(
        ..., description="Goal outcome to record"
    )
    summary: str = Field(..., min_length=1, description="Concise outcome summary")
    evidence: list[GoalProofInput] = Field(
        default_factory=list,
        description="Concrete observed proof for evidence or completion",
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
        if session.goal_state.status.value != "active":
            return ToolResult.error_result(
                "Resume the goal before recording progress or completing it."
            )

        if params.action == "record_evidence":
            session.record_goal_evidence(
                params.summary,
                evidence=[item.to_goal_proof() for item in params.evidence],
            )
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
        milestones = session.goal_state.milestones
        if not milestones:
            return ToolResult.error_result(
                "Completion requires a goal plan. Set concrete milestones with "
                "goal_progress before completing this goal.",
                metadata={"action": params.action},
            )
        pending = [item.title for item in milestones if not item.completed]
        if pending:
            return ToolResult.error_result(
                "Completion requires every goal milestone to be complete. Remaining: "
                + "; ".join(pending),
                metadata={"action": params.action},
            )
        session.complete_goal(
            params.summary,
            evidence=[item.to_goal_proof() for item in params.evidence],
        )
        return ToolResult.success_result(
            "Goal completed with recorded evidence.",
            metadata={"action": params.action},
        )
