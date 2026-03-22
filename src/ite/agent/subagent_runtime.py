from __future__ import annotations

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolResult
from ite.tools.subagent import SubagentTool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SubagentRun:
    run_id: str
    subagent: str
    goal: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    parent_session_id: str | None = None
    parent_tool_call_id: str | None = None
    child_session_id: str | None = None
    duration_ms: int | None = None
    child_turn_count: int = 0
    termination: str | None = None
    tools_used: list[str] = field(default_factory=list)
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubagentRuntime:
    def __init__(self, *, config: Config, session_id: str, tool_registry) -> None:
        self.config = config
        self.session_id = session_id
        self.tool_registry = tool_registry
        self._runs: dict[str, SubagentRun] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._counter = 0

    def list_runs(self, *, statuses: set[str] | None = None) -> list[SubagentRun]:
        runs = list(self._runs.values())
        if statuses:
            runs = [run for run in runs if run.status in statuses]
        runs.sort(key=lambda run: (run.created_at, run.run_id))
        return runs

    def get_run(self, run_id: str) -> SubagentRun | None:
        return self._runs.get(run_id)

    def _next_run_id(self) -> str:
        self._counter += 1
        return f"subrun_{self._counter:04d}"

    async def spawn(
        self,
        *,
        subagent: str,
        goal: str,
        parent_tool_call_id: str | None,
    ) -> SubagentRun:
        tool_name = f"subagent_{subagent}"
        tool = self.tool_registry.get(tool_name)
        if not isinstance(tool, SubagentTool):
            available = sorted(
                t.name.removeprefix("subagent_")
                for t in self.tool_registry.get_tools()
                if isinstance(t, SubagentTool)
            )
            raise ValueError(
                f"Unknown subagent '{subagent}'. Available subagents: {', '.join(available)}"
            )

        run_id = self._next_run_id()
        now = _utcnow().isoformat()
        run = SubagentRun(
            run_id=run_id,
            subagent=subagent,
            goal=goal,
            status="queued",
            created_at=now,
            parent_session_id=self.session_id,
            parent_tool_call_id=parent_tool_call_id,
        )
        self._runs[run_id] = run

        async def _runner() -> None:
            started_at = _utcnow()
            run.status = "running"
            run.started_at = started_at.isoformat()
            try:
                result = await tool.execute(
                    ToolInvocation(
                        params={"goal": goal},
                        cwd=Path(self.config.cwd),
                        call_id=parent_tool_call_id,
                        session_id=self.session_id,
                    )
                )
                self._apply_result(run, result, started_at=started_at)
            except asyncio.CancelledError:
                finished_at = _utcnow()
                run.status = "cancelled"
                run.termination = "cancelled"
                run.finished_at = finished_at.isoformat()
                run.duration_ms = max(
                    0,
                    int((finished_at - started_at).total_seconds() * 1000),
                )
                raise
            except Exception as exc:
                finished_at = _utcnow()
                run.status = "failed"
                run.termination = "error"
                run.error = str(exc)
                run.finished_at = finished_at.isoformat()
                run.duration_ms = max(
                    0,
                    int((finished_at - started_at).total_seconds() * 1000),
                )

        self._tasks[run_id] = asyncio.create_task(_runner(), name=run_id)
        return run

    def _apply_result(
        self,
        run: SubagentRun,
        result: ToolResult,
        *,
        started_at: datetime,
    ) -> None:
        result_payload = (
            result.metadata.get("subagent_result", {})
            if isinstance(result.metadata, dict)
            else {}
        )
        trace_payload = (
            result.metadata.get("subagent_trace", {})
            if isinstance(result.metadata, dict)
            else {}
        )

        run.child_session_id = str(trace_payload.get("child_session_id") or "") or None
        run.child_turn_count = int(trace_payload.get("child_turn_count") or 0)
        run.termination = str(trace_payload.get("termination") or result_payload.get("termination") or "") or None
        run.tools_used = [
            str(item)
            for item in result_payload.get("tools_used", [])
            if str(item).strip()
        ]
        run.summary = str(result_payload.get("summary") or "").strip()
        run.findings = [
            str(item).strip()
            for item in result_payload.get("findings", [])
            if str(item).strip()
        ]
        run.actions = [
            str(item).strip()
            for item in result_payload.get("actions", [])
            if str(item).strip()
        ]
        run.error = result.error

        finished_at = _utcnow()
        run.finished_at = finished_at.isoformat()
        run.duration_ms = (
            int(trace_payload["duration_ms"])
            if isinstance(trace_payload.get("duration_ms"), int)
            else max(0, int((finished_at - started_at).total_seconds() * 1000))
        )
        if result.success:
            run.status = "completed"
        elif run.termination == "timeout":
            run.status = "timeout"
        else:
            run.status = "failed"

    async def wait(
        self,
        *,
        run_ids: list[str] | None,
        timeout_seconds: float,
        return_when: str,
    ) -> dict[str, Any]:
        selected_ids = run_ids or list(self._runs.keys())
        selected_ids = [run_id for run_id in selected_ids if run_id in self._runs]
        selected_tasks = {
            run_id: task
            for run_id, task in self._tasks.items()
            if run_id in selected_ids and not task.done()
        }

        if selected_tasks:
            done, pending = await asyncio.wait(
                selected_tasks.values(),
                timeout=timeout_seconds,
                return_when=(
                    asyncio.FIRST_COMPLETED
                    if return_when == "first_completed"
                    else asyncio.ALL_COMPLETED
                ),
            )
            done_ids = [
                run_id
                for run_id, task in selected_tasks.items()
                if task in done
            ]
            pending_ids = [
                run_id
                for run_id, task in selected_tasks.items()
                if task in pending
            ]
        else:
            done_ids = [run_id for run_id in selected_ids if run_id in self._runs]
            pending_ids = []

        runs = [self._runs[run_id].to_dict() for run_id in selected_ids if run_id in self._runs]
        return {
            "completed_run_ids": done_ids,
            "pending_run_ids": pending_ids,
            "runs": runs,
        }

    async def cancel(self, *, run_ids: list[str] | None) -> dict[str, Any]:
        selected_ids = run_ids or list(self._tasks.keys())
        cancelled: list[str] = []
        for run_id in selected_ids:
            task = self._tasks.get(run_id)
            if task is None or task.done():
                continue
            run = self._runs.get(run_id)
            if run is not None and run.status in {"queued", "running"}:
                finished_at = _utcnow()
                run.status = "cancelled"
                run.termination = "cancelled"
                run.finished_at = finished_at.isoformat()
                if run.started_at:
                    started_at = datetime.fromisoformat(run.started_at)
                    run.duration_ms = max(
                        0,
                        int((finished_at - started_at).total_seconds() * 1000),
                    )
                else:
                    run.duration_ms = 0
            task.cancel()
            cancelled.append(run_id)
        if cancelled:
            await asyncio.gather(
                *(self._tasks[run_id] for run_id in cancelled),
                return_exceptions=True,
            )
        return {
            "cancelled_run_ids": cancelled,
            "runs": [self._runs[run_id].to_dict() for run_id in selected_ids if run_id in self._runs],
        }

    async def shutdown(self) -> None:
        await self.cancel(run_ids=list(self._tasks.keys()))
