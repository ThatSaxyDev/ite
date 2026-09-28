from __future__ import annotations

from typing import Awaitable, Callable, Any

from pydantic import BaseModel, Field

from ite.config.config import Config
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class PlanQuestionParams(BaseModel):
    question: str = Field(..., description="Question to ask the user.")
    options: list[str] = Field(
        ..., min_length=2, max_length=4, description="2-4 mutually exclusive options."
    )
    recommended_index: int | None = Field(
        None,
        ge=0,
        description="0-based index of recommended option.",
    )
    allow_free_text: bool = Field(
        True,
        description="Whether user can provide free-text instead of picking one option.",
    )


class PlanQuestionTool(Tool):
    name = "plan_question"
    description = (
        "Ask the user a structured planning question with 2-4 options and a recommended choice. "
        "Use this while in Plan mode before finalizing the implementation plan."
    )
    kind = ToolKind.MEMORY
    schema = PlanQuestionParams

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.question_callback: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return False

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        payload = PlanQuestionParams(**invocation.params)
        if self.question_callback is None:
            return ToolResult.error_result("Plan question callback not configured")

        recommended_index = payload.recommended_index
        if recommended_index is not None and recommended_index >= len(payload.options):
            return ToolResult.error_result("recommended_index is out of range for options")

        answer = await self.question_callback(
            {
                "question": payload.question,
                "options": payload.options,
                "recommended_index": recommended_index,
                "allow_free_text": payload.allow_free_text,
            }
        )

        selected_option = str(answer.get("selected_option") or "").strip()
        free_text = str(answer.get("free_text") or "").strip()
        selected_index = answer.get("selected_index")

        if selected_option:
            output = selected_option
        elif free_text:
            output = free_text
        else:
            return ToolResult.error_result("No answer provided for plan question")

        metadata = {
            "selected_option": selected_option or None,
            "free_text": free_text or None,
            "selected_index": selected_index,
            "question": payload.question,
        }

        return ToolResult.success_result(output, metadata=metadata)
