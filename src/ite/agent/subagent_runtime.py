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
from ite.ui.tool_narrative import describe_tool_activity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CircuitOpenError(RuntimeError):
    def __init__(self, *, subagent: str, reopen_at: datetime, failure_count: int) -> None:
        self.subagent = subagent
        self.reopen_at = reopen_at
        self.failure_count = failure_count
        super().__init__(
            f"Subagent '{subagent}' is temporarily paused after repeated failures. "
            f"Retry after {reopen_at.isoformat()}."
        )


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
    current_activity: str = ""
    last_update_at: str | None = None
    activity_history: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubagentRuntime:
    MAX_TERMINAL_RUNS = 50
    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_WINDOW_SECONDS = 600
    CIRCUIT_OPEN_SECONDS = 300

    def __init__(self, *, config: Config, session_id: str, tool_registry) -> None:
        self.config = config
        self.session_id = session_id
        self.tool_registry = tool_registry
        self._runs: dict[str, SubagentRun] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._counter = 0
        self._failure_history: dict[str, list[datetime]] = {}
        self._circuit_open_until: dict[str, datetime] = {}

    def _drop_finished_task(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is None or not task.done():
            return
        self._tasks.pop(run_id, None)

    def _prune_failure_history(self, subagent: str, *, now: datetime | None = None) -> list[datetime]:
        current = now or _utcnow()
        cutoff = current.timestamp() - self.CIRCUIT_WINDOW_SECONDS
        kept = [
            ts for ts in self._failure_history.get(subagent, [])
            if ts.timestamp() >= cutoff
        ]
        if kept:
            self._failure_history[subagent] = kept
        else:
            self._failure_history.pop(subagent, None)
        return kept

    def _is_circuit_open(self, subagent: str) -> tuple[bool, datetime | None, int]:
        now = _utcnow()
        failures = self._prune_failure_history(subagent, now=now)
        reopen_at = self._circuit_open_until.get(subagent)
        if reopen_at is None:
            return False, None, len(failures)
        if reopen_at <= now:
            self._circuit_open_until.pop(subagent, None)
            return False, None, len(failures)
        return True, reopen_at, len(failures)

    def _record_terminal_outcome(self, *, subagent: str, status: str) -> None:
        now = _utcnow()
        if status == "completed":
            self._failure_history.pop(subagent, None)
            self._circuit_open_until.pop(subagent, None)
            return
        if status not in {"failed", "timeout"}:
            return
        failures = self._prune_failure_history(subagent, now=now)
        failures.append(now)
        self._failure_history[subagent] = failures
        if len(failures) >= self.CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until[subagent] = datetime.fromtimestamp(
                now.timestamp() + self.CIRCUIT_OPEN_SECONDS,
                tz=timezone.utc,
            )

    def _prune_terminal_runs(self) -> None:
        terminal_statuses = {"completed", "failed", "timeout", "cancelled"}
        terminal_runs = [
            run
            for run in self._runs.values()
            if run.status in terminal_statuses
        ]
        if len(terminal_runs) <= self.MAX_TERMINAL_RUNS:
            return
        terminal_runs.sort(
            key=lambda run: (
                run.finished_at or run.created_at,
                run.run_id,
            )
        )
        overflow = len(terminal_runs) - self.MAX_TERMINAL_RUNS
        for run in terminal_runs[:overflow]:
            self._runs.pop(run.run_id, None)

    @staticmethod
    def _goal_key(goal: str) -> str:
        return " ".join(str(goal).strip().lower().split())

    def _set_activity(self, run: SubagentRun, message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        now = _utcnow().isoformat()
        run.current_activity = text
        run.last_update_at = now
        if run.activity_history and run.activity_history[-1].get("message") == text:
            run.activity_history[-1]["at"] = now
            return
        run.activity_history.append({"at": now, "message": text})
        if len(run.activity_history) > 6:
            run.activity_history = run.activity_history[-6:]

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
    ) -> tuple[SubagentRun, bool]:
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

        goal_key = self._goal_key(goal)
        for existing in self.list_runs(statuses={"queued", "running"}):
            if existing.subagent != subagent:
                continue
            if self._goal_key(existing.goal) != goal_key:
                continue
            return existing, True

        circuit_open, reopen_at, failure_count = self._is_circuit_open(subagent)
        if circuit_open and reopen_at is not None:
            raise CircuitOpenError(
                subagent=subagent,
                reopen_at=reopen_at,
                failure_count=failure_count,
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
            run.last_update_at = run.started_at
            self._set_activity(run, "Starting specialist session.")

            async def _progress(update: dict[str, Any]) -> None:
                phase = str(update.get("phase") or "").strip()
                if phase == "session_started":
                    child_session_id = str(update.get("child_session_id") or "").strip()
                    if child_session_id:
                        run.child_session_id = child_session_id
                    self._set_activity(run, "Session started.")
                    return
                if phase == "tool_call_start":
                    tool_name = str(update.get("tool_name") or "").strip()
                    arguments = update.get("arguments", {})
                    if tool_name:
                        self._set_activity(
                            run,
                            describe_tool_activity(
                                tool_name,
                                arguments if isinstance(arguments, dict) else {},
                                stage="start",
                            ),
                        )
                    return
                if phase == "text_complete":
                    summary = str(update.get("summary") or "").strip()
                    if summary:
                        self._set_activity(run, "Drafted specialist response.")
                    return
                if phase == "agent_error":
                    err = str(update.get("error") or "").strip()
                    self._set_activity(run, err or "Specialist failed.")
                    return
                if phase == "agent_end":
                    self._set_activity(run, "Specialist finished.")
                    return
                if phase == "retrying":
                    attempt = int(update.get("attempt") or 0)
                    reason = str(update.get("reason") or "retry").strip()
                    label = f"Retrying specialist after {reason}"
                    if attempt > 0:
                        label += f" (attempt {attempt})"
                    label += "."
                    self._set_activity(run, label)
                    return

            try:
                result = await tool._execute_with_progress(  # type: ignore[attr-defined]
                    ToolInvocation(
                        params={"goal": goal},
                        cwd=Path(self.config.cwd),
                        call_id=parent_tool_call_id,
                        session_id=self.session_id,
                    ),
                    progress_callback=_progress,
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
                self._set_activity(run, "Specialist cancelled.")
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
                self._set_activity(run, run.error)
                self._record_terminal_outcome(subagent=run.subagent, status=run.status)
            finally:
                self._prune_terminal_runs()

        task = asyncio.create_task(_runner(), name=run_id)
        task.add_done_callback(lambda _task, rid=run_id: self._drop_finished_task(rid))
        self._tasks[run_id] = task
        return run, False

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
        if run.summary:
            self._set_activity(run, run.summary)
        elif result.error:
            self._set_activity(run, result.error)
        else:
            self._set_activity(run, "Specialist finished.")
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
        self._record_terminal_outcome(subagent=run.subagent, status=run.status)
        self._prune_terminal_runs()

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
                self._set_activity(run, "Specialist cancelled.")
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
