from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ite.tools.base import Tool
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolKind
from ite.tools.base import ToolMetadata
from ite.tools.base import ToolResult
from ite.tools.base import ToolRiskLevel


class SkillsParams(BaseModel):
    action: str = Field(
        "list",
        description="Action to perform: list, show, activate, deactivate, or clear.",
    )
    skill: str | None = Field(
        None,
        description="Skill name or identifier for show, activate, or deactivate.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "SkillsParams":
        action = self.action.strip().lower()
        if action not in {"list", "show", "activate", "deactivate", "clear"}:
            raise ValueError("action must be one of: list, show, activate, deactivate, clear")
        if action in {"show", "activate", "deactivate"} and not str(self.skill or "").strip():
            raise ValueError("skill is required for show, activate, and deactivate")
        return self


class SkillsTool(Tool):
    name = "skills"
    description = "List, inspect, activate, or deactivate Agent Skills discovered from SKILL.md bundles."
    kind = ToolKind.READ
    schema = SkillsParams

    def __init__(self, config):
        super().__init__(config)
        self._session: Any | None = None

    def set_session(self, session: Any | None) -> None:
        self._session = session

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        action = str(params.get("action") or "list").strip().lower()
        mutating = action in {"activate", "deactivate", "clear"}
        return ToolMetadata(
            mutating=mutating,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=not mutating,
            supports_subagent_use=False,
            output_schema={
                "type": "object",
                "required": ["action", "active_skills", "available_count"],
                "properties": {
                    "action": {"type": "string"},
                    "active_skills": {"type": "array", "items": {"type": "string"}},
                    "available_count": {"type": "integer"},
                    "skill": {"type": "string"},
                    "instructions": {"type": "string"},
                },
            },
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        if self._session is None:
            return ToolResult.error_result("Skills are unavailable because no active session is attached.")

        params = SkillsParams(**invocation.params)
        action = params.action.strip().lower()
        session = self._session
        if hasattr(session, "refresh_skills"):
            session.refresh_skills()
        available = session.list_available_skills()
        active = [skill.identifier for skill in session.get_active_skills()]

        if action == "list":
            payload = {
                "action": "list",
                "available_count": len(available),
                "active_skills": active,
                "skills": available,
            }
            return ToolResult.success_result(json.dumps(payload, ensure_ascii=False, indent=2))

        if action == "show":
            skill = session.resolve_skill(params.skill or "")
            if skill is None:
                return ToolResult.error_result(f"Skill not found: {params.skill}")
            payload = {
                "action": "show",
                "available_count": len(available),
                "active_skills": active,
                "skill": skill.identifier,
                "name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
            }
            return ToolResult.success_result(json.dumps(payload, ensure_ascii=False, indent=2))

        if action == "activate":
            skill = session.activate_skill(params.skill or "")
            if skill is None:
                return ToolResult.error_result(f"Skill not found: {params.skill}")
            payload = {
                "action": "activate",
                "available_count": len(available),
                "active_skills": [item.identifier for item in session.get_active_skills()],
                "skill": skill.identifier,
                "name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
            }
            return ToolResult.success_result(json.dumps(payload, ensure_ascii=False, indent=2))

        if action == "deactivate":
            removed = session.deactivate_skill(params.skill or "")
            if removed is None:
                return ToolResult.error_result(f"Skill not active or not found: {params.skill}")
            payload = {
                "action": "deactivate",
                "available_count": len(available),
                "active_skills": [item.identifier for item in session.get_active_skills()],
                "skill": removed.identifier,
            }
            return ToolResult.success_result(json.dumps(payload, ensure_ascii=False, indent=2))

        session.clear_active_skills()
        payload = {
            "action": "clear",
            "available_count": len(available),
            "active_skills": [],
        }
        return ToolResult.success_result(json.dumps(payload, ensure_ascii=False, indent=2))
