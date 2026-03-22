from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from ite.agent.subagent_runtime import SubagentRuntime
from ite.tools.base import Tool
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolMetadata
from ite.tools.base import ToolResult
from ite.tools.base import ToolRiskLevel


class SpawnSubagentParams(BaseModel):
    subagent: str = Field(..., description="Registered subagent name without the `subagent_` prefix.")
    goal: str = Field(..., description="Task to delegate to the selected subagent.")


class WaitSubagentParams(BaseModel):
    run_ids: list[str] | None = Field(
        None,
        description="Optional run ids to wait for. Defaults to all known runs in this session.",
    )
    timeout_seconds: float = Field(
        300,
        ge=0,
        le=3600,
        description="Maximum time to wait before returning pending runs.",
    )
    return_when: str = Field(
        "all_completed",
        description="Wait mode: `all_completed` or `first_completed`.",
    )


class ListSubagentsParams(BaseModel):
    status: str | None = Field(
        None,
        description="Optional comma-separated status filter (queued,running,completed,failed,timeout,cancelled).",
    )


class CancelSubagentParams(BaseModel):
    run_ids: list[str] | None = Field(
        None,
        description="Optional run ids to cancel. Defaults to all active runs in this session.",
    )


class _SubagentRuntimeTool(Tool):
    runtime: SubagentRuntime | None = None

    def set_runtime(self, runtime: SubagentRuntime) -> None:
        self.runtime = runtime

    def _require_runtime(self) -> SubagentRuntime:
        if self.runtime is None:
            raise RuntimeError("Subagent runtime is not initialized for this session.")
        return self.runtime


class SpawnSubagentTool(_SubagentRuntimeTool):
    name = "spawn_subagent"
    description = "Start a subagent run in the background so the parent can continue and wait later."
    schema = SpawnSubagentParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=False,
            supports_subagent_use=False,
            output_schema={"type": "object"},
        )

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return True

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = SpawnSubagentParams(**invocation.params)
        runtime = self._require_runtime()
        run = await runtime.spawn(
            subagent=params.subagent,
            goal=params.goal,
            parent_tool_call_id=invocation.call_id,
        )
        payload = {
            "spawned": True,
            "run": run.to_dict(),
        }
        return ToolResult.success_result(
            json.dumps(payload, indent=2),
            metadata=payload,
        )


class WaitSubagentTool(_SubagentRuntimeTool):
    name = "wait_subagent"
    description = "Wait for one or more previously spawned subagent runs to complete."
    schema = WaitSubagentParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=False,
            output_schema={"type": "object"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WaitSubagentParams(**invocation.params)
        runtime = self._require_runtime()
        result = await runtime.wait(
            run_ids=params.run_ids,
            timeout_seconds=params.timeout_seconds,
            return_when=params.return_when,
        )
        return ToolResult.success_result(
            json.dumps(result, indent=2),
            metadata=result,
        )


class ListSubagentsTool(_SubagentRuntimeTool):
    name = "list_subagents"
    description = "List spawned subagent runs and their current statuses."
    schema = ListSubagentsParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=False,
            output_schema={"type": "object"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ListSubagentsParams(**invocation.params)
        runtime = self._require_runtime()
        statuses = None
        if isinstance(params.status, str) and params.status.strip():
            statuses = {
                part.strip()
                for part in params.status.split(",")
                if part.strip()
            }
        runs = [run.to_dict() for run in runtime.list_runs(statuses=statuses)]
        payload = {
            "runs": runs,
            "count": len(runs),
        }
        return ToolResult.success_result(
            json.dumps(payload, indent=2),
            metadata=payload,
        )


class CancelSubagentTool(_SubagentRuntimeTool):
    name = "cancel_subagent"
    description = "Cancel one or more active subagent runs."
    schema = CancelSubagentParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=False,
            supports_subagent_use=False,
            output_schema={"type": "object"},
        )

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return True

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = CancelSubagentParams(**invocation.params)
        runtime = self._require_runtime()
        result = await runtime.cancel(run_ids=params.run_ids)
        return ToolResult.success_result(
            json.dumps(result, indent=2),
            metadata=result,
        )
