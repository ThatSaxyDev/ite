"""Structured milestones and proof for a durable Goal."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ite.agent.goal import GoalProof
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class GoalProofInput(BaseModel):
    """A proof item that can be shown plainly in the Goal panel."""

    kind: Literal["command", "ci", "url", "artifact", "other"] = Field(
        ..., description="What kind of proof this is"
    )
    label: str = Field(..., min_length=1, description="Short human-readable result")
    reference: str = Field(
        ...,
        min_length=1,
        description="Command, URL, artifact path, or CI run reference",
    )
    status: Literal["passed", "recorded"] = Field(
        default="recorded", description="Whether iTE observed a successful result"
    )

    def to_goal_proof(self) -> GoalProof:
        return GoalProof(
            kind=self.kind,
            label=self.label.strip(),
            reference=self.reference.strip(),
            status=self.status,
        )


class GoalProgressParams(BaseModel):
    action: Literal["set_plan", "complete_milestone"] = Field(
        ..., description="Create the goal plan or complete one of its milestones"
    )
    milestones: list[str] = Field(
        default_factory=list,
        description="One to six concrete, outcome-oriented milestones for set_plan",
    )
    milestone_id: str | None = Field(
        default=None, description="The milestone id to complete"
    )
    summary: str | None = Field(
        default=None, description="Concise description of the completed milestone"
    )
    evidence: list[GoalProofInput] = Field(
        default_factory=list,
        description="Observed proof for the milestone, such as CI, a URL, or a command",
    )


class GoalProgressTool(Tool):
    name = "goal_progress"
    description = (
        "Maintain the active goal's user-visible plan and proof. Before substantive "
        "work, set one to six concrete milestones that cover the objective. Complete "
        "each milestone only with concise observed proof."
    )
    kind = ToolKind.MEMORY
    schema = GoalProgressParams

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._session: Any | None = None

    def set_session(self, session: Any | None) -> None:
        self._session = session

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GoalProgressParams(**invocation.params)
        session = self._session
        if session is None or session.goal_state is None:
            return ToolResult.error_result("No active goal exists for this thread.")
        if session.goal_state.status.value != "active":
            return ToolResult.error_result(
                "Resume the goal before updating its plan or milestones."
            )

        if params.action == "set_plan":
            if not params.milestones:
                return ToolResult.error_result(
                    "A goal plan needs at least one milestone."
                )
            if len(params.milestones) > 6:
                return ToolResult.error_result(
                    "A goal plan can have at most six milestones."
                )
            if any(item.completed for item in session.goal_state.milestones):
                return ToolResult.error_result(
                    "Do not replace a plan after work has been marked complete. "
                    "Complete the remaining milestones or report a blocker."
                )
            try:
                milestones = session.set_goal_milestones(params.milestones)
            except ValueError as exc:
                return ToolResult.error_result(str(exc))
            return ToolResult.success_result(
                f"Goal plan recorded with {len(milestones)} milestone(s).",
                metadata={"action": "set_plan", "count": len(milestones)},
            )

        if not params.milestone_id:
            return ToolResult.error_result(
                "milestone_id is required to complete a milestone."
            )
        if not params.evidence:
            return ToolResult.error_result(
                "Completing a milestone requires at least one observed proof item."
            )
        try:
            milestone = session.complete_goal_milestone(
                params.milestone_id,
                summary=(params.summary or "").strip(),
                evidence=[item.to_goal_proof() for item in params.evidence],
            )
        except ValueError as exc:
            return ToolResult.error_result(str(exc))
        return ToolResult.success_result(
            f"Completed milestone: {milestone.title}",
            metadata={
                "action": "complete_milestone",
                "milestone_id": milestone.milestone_id,
            },
        )
