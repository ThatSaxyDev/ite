import asyncio
import inspect
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Awaitable
from typing import Callable

from pydantic import BaseModel
from pydantic import Field

from ite.config.config import Config
from ite.tools.base import Tool
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolMetadata
from ite.tools.base import ToolResult
from ite.tools.base import ToolRiskLevel


class SubagentParams(BaseModel):
    goal: str = Field(
        ..., description="The specific task or goal for the subagent to achieve"
    )


@dataclass
class SubagentDefinition:
    name: str
    description: str
    goal_prompt: str
    allowed_tools: list[str] | None = None
    max_turns: int = 20
    timeout_seconds: float = 600
    inactivity_timeout_seconds: float = 120
    retry_attempts: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> "SubagentDefinition":
        """Create a SubagentDefinition from a parsed TOML dict."""
        required = ("name", "description", "goal_prompt")
        missing = [f for f in required if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        return cls(
            name=data["name"],
            description=data["description"],
            goal_prompt=data["goal_prompt"],
            allowed_tools=data.get("allowed_tools"),
            max_turns=data.get("max_turns", 20),
            timeout_seconds=data.get("timeout_seconds", 600),
            inactivity_timeout_seconds=data.get("inactivity_timeout_seconds", 120),
            retry_attempts=data.get("retry_attempts", 1),
        )


class SubagentTool(Tool):
    def __init__(
        self,
        config: Config,
        definition: SubagentDefinition,
        allowed_tools: list[str] | None = None,
        allows_mutation: bool | None = None,
    ):
        super().__init__(config)
        self.definition = definition
        self.allowed_tools = list(allowed_tools) if allowed_tools is not None else None
        self.allows_mutation = allows_mutation
        self._live_progress: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return f"subagent_{self.definition.name}"

    @property
    def description(self) -> str:
        return self.definition.description

    schema = SubagentParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        mutating = self.is_mutating(params)
        return ToolMetadata(
            mutating=mutating,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=not mutating,
            supports_subagent_use=False,
            output_schema={
                "type": "object",
                "required": ["status", "subagent", "termination", "tools_used", "summary"],
                "properties": {
                    "status": {"type": "string"},
                    "subagent": {"type": "string"},
                    "termination": {"type": "string"},
                    "tools_used": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "actions": {"type": "array", "items": {"type": "string"}},
                },
            },
        )

    def is_mutating(self, params: dict[str, Any]) -> bool:
        # Treat subagents as non-mutating in plan mode only when their effective
        # allowlist is fully read-only.
        if self.allows_mutation is not None:
            return self.allows_mutation

        allowed = self.allowed_tools if self.allowed_tools is not None else self.definition.allowed_tools
        if not allowed:
            return True

        # Fallback for direct construction in tests or callers that do not pass
        # registry-derived metadata. The registry path is authoritative.
        mutating_tools = {
            "write_file",
            "edit",
            "apply_patch",
            "shell",
            "memory",
            "todos",
            "web_search",
            "web_fetch",
            "mcp",
        }
        return any(tool in mutating_tools for tool in allowed)

    def _set_live_progress(
        self,
        *,
        call_id: str,
        message: str,
        child_session_id: str | None = None,
    ) -> None:
        text = str(message).strip()
        if not text:
            return
        now = datetime.now(timezone.utc).isoformat()
        state = self._live_progress.setdefault(
            call_id,
            {
                "current_activity": "",
                "last_update_at": None,
                "child_session_id": None,
                "activity_history": [],
            },
        )
        state["current_activity"] = text
        state["last_update_at"] = now
        if child_session_id:
            state["child_session_id"] = child_session_id
        history = state.setdefault("activity_history", [])
        if history and history[-1].get("message") == text:
            history[-1]["at"] = now
        else:
            history.append({"at": now, "message": text})
            if len(history) > 6:
                del history[:-6]

    def get_live_progress(self, call_id: str) -> dict[str, Any] | None:
        state = self._live_progress.get(call_id)
        return dict(state) if isinstance(state, dict) else None

    def clear_live_progress(self, call_id: str) -> None:
        self._live_progress.pop(call_id, None)

    async def _run_subagent_agent(
        self,
        *,
        prompt: str,
        subagent_config: Config,
        tool_calls: list[str],
        agent=None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> tuple[str, str | None, str | None, str | None, int]:
        from ite.agent.events import AgentEventType
        from ite.agent.agent import Agent

        final_response: str | None = None
        error: str | None = None
        terminate_response = "goal"
        child_session_id: str | None = None
        child_turn_count = 0

        async def _consume_agent(run_agent: Agent) -> None:
            nonlocal final_response, error, terminate_response, child_session_id, child_turn_count
            if run_agent.session is not None:
                child_session_id = run_agent.session.session_id
                if progress_callback is not None and agent is None:
                    maybe = progress_callback(
                        {
                            "phase": "session_started",
                            "child_session_id": child_session_id,
                        }
                    )
                    if maybe is not None:
                        await maybe
            async for event in run_agent.run(prompt):
                if event.type == AgentEventType.TOOL_CALL_START:
                    tool_name = event.data.get("name")
                    tool_calls.append(tool_name)
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "tool_call_start",
                                "tool_name": tool_name,
                                "arguments": event.data.get("arguments", {}),
                            }
                        )
                        if maybe is not None:
                            await maybe
                elif event.type == AgentEventType.TEXT_COMPLETE:
                    if bool(event.data.get("final", True)):
                        final_response = event.data.get("content")
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "text_complete",
                                "summary": event.data.get("content"),
                                "final": bool(event.data.get("final", True)),
                            }
                        )
                        if maybe is not None:
                            await maybe
                elif event.type == AgentEventType.AGENT_END:
                    if final_response is None:
                        final_response = event.data.get("response")
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "agent_end",
                                "summary": final_response,
                            }
                        )
                        if maybe is not None:
                            await maybe
                elif event.type == AgentEventType.AGENT_ERROR:
                    terminate_response = "error"
                    error = event.data.get("error", "Unknown error")
                    if final_response is None:
                        final_response = f"Sub-agent failed: {error}"
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "agent_error",
                                "error": error,
                            }
                        )
                        if maybe is not None:
                            await maybe
                    break
            if run_agent.session is not None:
                child_turn_count = run_agent.session.turn_count

        if agent is not None:
            await _consume_agent(agent)
        else:
            async with Agent(subagent_config) as child_agent:
                await _consume_agent(child_agent)

        return terminate_response, final_response, error, child_session_id, child_turn_count

    def _normalize_response_payload(self, response_text: str) -> tuple[str, list[str], list[str]]:
        """Extract summary, findings, actions from subagent response."""
        text = (response_text or "").strip()
        if not text:
            return "No response", [], []

        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None

        # Special case: init_investigator returns AGENTS.md content which may look like JSON
        # but should be treated as raw text (the markdown contains code blocks that parse as JSON)
        # If "# AGENTS.md" appears anywhere in the text, treat it as the raw summary
        if "# AGENTS.md" in text or text.startswith("# "):
            findings: list[str] = []
            actions: list[str] = []
            for line in text.splitlines():
                stripped = line.strip()
                lower = stripped.lower()
                if lower.startswith(("finding:", "- finding:", "* finding:")):
                    findings.append(stripped.split(":", 1)[-1].strip())
                if lower.startswith(("action:", "- action:", "* action:", "next:", "- next:")):
                    actions.append(stripped.split(":", 1)[-1].strip())
            return text, findings, actions

        if isinstance(parsed, dict):
            summary = str(parsed.get("summary") or parsed.get("answer") or text).strip() or "No response"
            raw_findings = parsed.get("findings") or []
            raw_actions = parsed.get("actions") or parsed.get("next_steps") or []
            findings = [str(item).strip() for item in raw_findings if str(item).strip()]
            actions = [str(item).strip() for item in raw_actions if str(item).strip()]
            return summary, findings, actions

        findings = []
        actions = []
        for line in text.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith(("finding:", "- finding:", "* finding:")):
                findings.append(stripped.split(":", 1)[-1].strip())
            if lower.startswith(("action:", "- action:", "* action:", "next:", "- next:")):
                actions.append(stripped.split(":", 1)[-1].strip())
        return text, findings, actions

    @staticmethod
    def _is_retryable_failure(terminate_response: str, error: str | None) -> bool:
        if terminate_response == "timeout":
            return True
        normalized = str(error or "").strip().lower()
        return "maximum turns" in normalized

    @staticmethod
    def _truncate_text(value: str | None, *, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _attempt_context_lines(self, attempt: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        termination = str(attempt.get("termination") or "unknown").strip()
        error = str(attempt.get("error") or "").strip() or "none"
        lines.append(f"- Attempt {attempt.get('attempt')}: termination={termination} error={error}")

        summary_text = str(attempt.get("summary") or "").strip()
        if summary_text:
            lines.append(f"  Partial summary: {self._truncate_text(summary_text, limit=400)}")

        findings = [
            str(item).strip()
            for item in (attempt.get("findings") or [])
            if str(item).strip()
        ]
        if findings:
            lines.append(
                "  Partial findings: "
                + "; ".join(self._truncate_text(item, limit=160) for item in findings[:4])
            )

        actions = [
            str(item).strip()
            for item in (attempt.get("actions") or [])
            if str(item).strip()
        ]
        if actions:
            lines.append(
                "  Partial next actions: "
                + "; ".join(self._truncate_text(item, limit=160) for item in actions[:4])
            )

        partial_output = str(attempt.get("final_response") or "").strip()
        if partial_output and partial_output != summary_text:
            lines.append(f"  Partial output: {self._truncate_text(partial_output, limit=700)}")

        activities = attempt.get("activities") or []
        if isinstance(activities, list) and activities:
            lines.append(
                "  Recent activity: "
                + " -> ".join(
                    self._truncate_text(str(item).strip(), limit=120)
                    for item in activities[-8:]
                    if str(item).strip()
                )
            )

        tool_calls = attempt.get("tool_calls") or []
        if isinstance(tool_calls, list) and tool_calls:
            lines.append(
                "  Tools used: " + ", ".join(str(item).strip() for item in tool_calls if str(item).strip())
            )
        return lines

    @staticmethod
    def _short_target_path(path: str | None) -> str:
        text = str(path or "").strip()
        if not text:
            return ""
        trimmed = text.rstrip("/").strip()
        if not trimmed or trimmed == ".":
            return "the workspace"
        return Path(trimmed).name or trimmed

    @staticmethod
    def _tool_call_activity(tool_name: str, arguments: dict[str, Any]) -> str:
        path = SubagentTool._short_target_path(arguments.get("path"))
        pattern = str(arguments.get("pattern") or "").strip()

        if tool_name == "read_file":
            if path:
                return f"Reading {path}."
            return "Reading workspace files."
        if tool_name == "grep":
            if path and path != "the workspace" and pattern:
                return f"Searching {path} for `{pattern}`."
            if pattern:
                return f"Searching code for `{pattern}`."
            return "Searching code."
        if tool_name == "glob":
            raw_pattern = str(arguments.get("pattern") or "").strip()
            if raw_pattern:
                return f"Finding files matching `{raw_pattern}`."
            return "Finding files."
        if tool_name == "list_dir":
            if path and path != "the workspace":
                return f"Looking in {path}."
            return "Looking through the workspace."
        return f"Using {tool_name}."

    def _build_attempt_prompt(
        self,
        *,
        goal: str,
        prior_attempts: list[dict[str, Any]],
    ) -> str:
        # Special handling for init_investigator to ensure it acts decisively
        init_directive = ""
        if self.definition.name == "init_investigator":
            init_directive = """
MANDATORY DIRECTIVE FOR INITIALIZATION:
- You MUST immediately investigate the project and output AGENTS.md
- Do NOT ask the user any questions
- Do NOT say "I need more information" - discover what you can from the files
- Do NOT apologize or explain your limitations
- Simply do your best with what you can find and output the AGENTS.md file
"""

        prompt = f"""You are a specialized sub-agent with a specific task to complete.

        {self.definition.goal_prompt}{init_directive}

        YOUR TASK:
        {goal}

        IMPORTANT:
        - Focus only on completing the specified task
        - Do not engage in unrelated actions
        - Once you have completed the task or have the answer, provide your final response
        - Be concise and direct in your output
        """

        if not prior_attempts:
            return prompt

        carryover_lines: list[str] = [
            "",
            "CONTINUATION CONTEXT FROM PRIOR ATTEMPT(S):",
            "- Continue from the work already completed below instead of restarting from scratch.",
            "- Reuse the inspected areas and activity trail when deciding the next step.",
            "- Treat prior partial findings and output as working notes that should be finished and refined.",
            "- Focus first on the unfinished parts that caused the prior attempt to stop.",
            "- Avoid redoing broad exploration unless it is necessary to finish the task.",
        ]
        for attempt in prior_attempts:
            carryover_lines.extend(self._attempt_context_lines(attempt))
        return prompt + "\n".join(carryover_lines)

    async def _execute_with_progress(
        self,
        invocation: ToolInvocation,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> ToolResult:
        class _InactiveSubagentTimeout(Exception):
            pass

        params = SubagentParams(**invocation.params)
        if not params.goal:
            return ToolResult.error_result("No goal specified for subagent")

        config_dict = self.config.to_dict()

        config_dict["max_turns"] = self.definition.max_turns

        if self.allowed_tools is not None:
            config_dict["allowed_tools"] = self.allowed_tools
        elif self.definition.allowed_tools:
            config_dict["allowed_tools"] = self.definition.allowed_tools

        subagent_config = Config(**config_dict)

        all_tool_calls: list[str] = []
        final_response: str | None = None
        error: str | None = None
        terminate_response = "goal"
        started_at = datetime.now(timezone.utc)
        run_id = f"sa_{uuid.uuid4().hex[:12]}"
        child_session_id: str | None = None
        child_turn_count = 0
        live_call_id = str(invocation.call_id or "").strip()
        prior_attempts: list[dict[str, Any]] = []
        retries_used = 0
        attempts_run = 0

        if live_call_id:
            self._set_live_progress(
                call_id=live_call_id,
                message="Starting specialist session.",
            )

        attempt_activities: list[str] = []
        progress_loop = asyncio.get_running_loop()
        last_progress_at = progress_loop.time()

        async def tracked_progress(update: dict[str, Any]) -> None:
            nonlocal child_session_id, last_progress_at
            last_progress_at = progress_loop.time()
            if live_call_id:
                phase = str(update.get("phase") or "").strip()
                if phase == "session_started":
                    child_session_id = str(update.get("child_session_id") or "").strip() or child_session_id
                    self._set_live_progress(
                        call_id=live_call_id,
                        message="Session started.",
                        child_session_id=child_session_id,
                    )
                elif phase == "tool_call_start":
                    tool_name = str(update.get("tool_name") or "").strip()
                    arguments = update.get("arguments", {})
                    if tool_name:
                        message = self._tool_call_activity(
                            tool_name,
                            arguments if isinstance(arguments, dict) else {},
                        )
                        self._set_live_progress(
                            call_id=live_call_id,
                            message=message,
                        )
                        attempt_activities.append(message)
                elif phase == "text_complete":
                    self._set_live_progress(
                        call_id=live_call_id,
                        message="Drafted specialist response.",
                    )
                    attempt_activities.append("Drafted specialist response.")
                elif phase == "agent_error":
                    self._set_live_progress(
                        call_id=live_call_id,
                        message=str(update.get("error") or "Specialist failed.").strip(),
                    )
                    attempt_activities.append(str(update.get("error") or "Specialist failed.").strip())
                elif phase == "agent_end":
                    self._set_live_progress(
                        call_id=live_call_id,
                        message="Specialist finished.",
                    )
                    attempt_activities.append("Specialist finished.")
                elif phase == "retrying":
                    reason = str(update.get("reason") or "retry").strip()
                    attempt = int(update.get("attempt") or 0)
                    label = f"Retrying specialist after {reason}"
                    if attempt > 0:
                        label += f" (attempt {attempt})"
                    label += "."
                    self._set_live_progress(
                        call_id=live_call_id,
                        message=label,
                    )
                    attempt_activities.append(label)
            if progress_callback is not None:
                maybe = progress_callback(update)
                if maybe is not None:
                    await maybe

        from ite.agent.agent import Agent

        async with Agent(subagent_config) as child_agent:
            if child_agent.session is not None:
                child_session_id = child_agent.session.session_id
                await tracked_progress(
                    {
                        "phase": "session_started",
                        "child_session_id": child_session_id,
                    }
                )

            for attempt_index in range(self.definition.retry_attempts + 1):
                attempts_run = attempt_index + 1
                tool_calls: list[str] = []
                attempt_activities = []
                prompt = self._build_attempt_prompt(
                    goal=params.goal,
                    prior_attempts=prior_attempts,
                )
                try:
                    runner_kwargs: dict[str, Any] = {
                        "prompt": prompt,
                        "subagent_config": subagent_config,
                        "tool_calls": tool_calls,
                    }
                    try:
                        parameters = inspect.signature(self._run_subagent_agent).parameters
                    except (TypeError, ValueError):
                        parameters = {}
                    if "agent" in parameters:
                        runner_kwargs["agent"] = child_agent
                    if "progress_callback" in parameters:
                        runner_kwargs["progress_callback"] = tracked_progress
                    last_progress_at = progress_loop.time()
                    runner_task = asyncio.create_task(self._run_subagent_agent(**runner_kwargs))
                    absolute_deadline = progress_loop.time() + self.definition.timeout_seconds
                    inactivity_timeout = max(0.0, float(self.definition.inactivity_timeout_seconds))

                    while True:
                        now = progress_loop.time()
                        remaining_total = absolute_deadline - now
                        if remaining_total <= 0:
                            raise asyncio.TimeoutError

                        remaining_wait = remaining_total
                        if inactivity_timeout > 0:
                            remaining_inactive = (last_progress_at + inactivity_timeout) - now
                            if remaining_inactive <= 0:
                                raise _InactiveSubagentTimeout
                            remaining_wait = min(remaining_wait, remaining_inactive)

                        done, _pending = await asyncio.wait(
                            {runner_task},
                            timeout=remaining_wait,
                            return_when=asyncio.ALL_COMPLETED,
                        )
                        if runner_task in done:
                            (
                                terminate_response,
                                final_response,
                                error,
                                child_session_id,
                                child_turn_count,
                            ) = await runner_task
                            break
                        if inactivity_timeout > 0 and (progress_loop.time() - last_progress_at) >= inactivity_timeout:
                            raise _InactiveSubagentTimeout
                        continue
                except asyncio.TimeoutError:
                    terminate_response = "timeout"
                    final_response = "Sub-agent timed out"
                    error = "Sub-agent timed out"
                    if live_call_id:
                        self._set_live_progress(
                            call_id=live_call_id,
                            message="Specialist timed out.",
                            child_session_id=child_session_id,
                        )
                    attempt_activities.append("Specialist timed out.")
                    if "runner_task" in locals() and not runner_task.done():
                        runner_task.cancel()
                        await asyncio.gather(runner_task, return_exceptions=True)
                except _InactiveSubagentTimeout:
                    terminate_response = "timeout"
                    final_response = "Sub-agent timed out after no progress"
                    error = "Sub-agent timed out after no progress"
                    if live_call_id:
                        self._set_live_progress(
                            call_id=live_call_id,
                            message="Specialist timed out after no progress.",
                            child_session_id=child_session_id,
                        )
                    attempt_activities.append("Specialist timed out after no progress.")
                    if "runner_task" in locals() and not runner_task.done():
                        runner_task.cancel()
                        await asyncio.gather(runner_task, return_exceptions=True)
                except Exception as e:
                    terminate_response = "error"
                    error = str(e)
                    final_response = f"Sub-agent failed: {e}"
                    if live_call_id:
                        self._set_live_progress(
                            call_id=live_call_id,
                            message=str(e),
                            child_session_id=child_session_id,
                        )
                    attempt_activities.append(str(e))

                all_tool_calls.extend(tool_calls)
                partial_summary, partial_findings, partial_actions = self._normalize_response_payload(final_response or "")
                should_retry = (
                    attempt_index < self.definition.retry_attempts
                    and self._is_retryable_failure(terminate_response, error)
                )
                if not should_retry:
                    break
                retries_used += 1
                prior_attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "termination": terminate_response,
                        "error": error,
                        "final_response": final_response,
                        "summary": partial_summary,
                        "findings": partial_findings,
                        "actions": partial_actions,
                        "activities": attempt_activities,
                        "tool_calls": list(tool_calls),
                    }
                )
                if live_call_id:
                    self._set_live_progress(
                        call_id=live_call_id,
                        message=f"Continuing specialist after {terminate_response} (attempt {attempt_index + 2}).",
                        child_session_id=child_session_id,
                    )
                if progress_callback is not None:
                    maybe = progress_callback(
                        {
                            "phase": "retrying",
                            "attempt": attempt_index + 2,
                            "reason": terminate_response,
                        }
                    )
                    if maybe is not None:
                        await maybe
                error = None

        response_text = final_response or ""
        summary, findings, actions = self._normalize_response_payload(response_text)
        finished_at = datetime.now(timezone.utc)
        duration_ms = max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        )
        trace_payload = {
            "run_id": run_id,
            "subagent": self.definition.name,
            "parent_tool_call_id": invocation.call_id,
            "parent_session_id": invocation.session_id,
            "child_session_id": child_session_id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "child_turn_count": child_turn_count,
            "tool_count": len(all_tool_calls),
            "attempt_count": attempts_run,
            "retries_used": retries_used,
            "recovered_after_retry": retries_used > 0 and not error and terminate_response != "timeout",
            "status": "ok" if not error and terminate_response != "timeout" else "error",
            "termination": terminate_response,
        }

        result_payload = {
            "status": trace_payload["status"],
            "subagent": self.definition.name,
            "termination": terminate_response,
            "tools_used": all_tool_calls,
            "summary": summary,
            "findings": findings,
            "actions": actions,
            "attempt_count": attempts_run,
            "retries_used": retries_used,
            "recovered_after_retry": trace_payload["recovered_after_retry"],
        }

        output = json.dumps(result_payload, indent=2)
        metadata = {
            "subagent_result": result_payload,
            "subagent_trace": trace_payload,
        }

        if terminate_response == "timeout":
            if live_call_id:
                self.clear_live_progress(live_call_id)
            return ToolResult.error_result(
                output=output,
                error=f"Sub-agent '{self.definition.name}' timed out",
                metadata=metadata,
            )

        if error:
            if live_call_id:
                self.clear_live_progress(live_call_id)
            return ToolResult.error_result(
                output=output,
                error=f"Sub-agent '{self.definition.name}' failed",
                metadata=metadata,
            )

        if live_call_id:
            self.clear_live_progress(live_call_id)
        return ToolResult.success_result(output, metadata=metadata)

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return await self._execute_with_progress(invocation, progress_callback=None)


CODEBASE_INVESTIGATOR = SubagentDefinition(
    name="codebase_investigator",
    description="Investigates the codebase to answer questions about code structure, patterns, and implementations",
    goal_prompt="""You are a codebase investigation specialist.
Your job is to explore and understand code to answer questions.
Use read_file, grep, glob, and list_dir to investigate.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
    retry_attempts=2,
)

CODE_REVIEWER = SubagentDefinition(
    name="code_reviewer",
    description="Reviews code changes and provides feedback on quality, bugs, and improvements",
    goal_prompt="""You are a code review specialist.
Your job is to review code and provide constructive feedback.
Look for bugs, code smells, security issues, and improvement opportunities.
    Use read_file, list_dir and grep to examine the code.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "list_dir"],
    max_turns=30,
    timeout_seconds=600,
    inactivity_timeout_seconds=120,
    retry_attempts=2,
)

TOOLING_GUARDIAN = SubagentDefinition(
    name="tooling_guardian",
    description="Audits tool configuration, discovery health, and safety/routing integrity",
    goal_prompt="""You are a tooling integrity specialist.
Audit tool setup, safety boundaries, and runtime routing assumptions.
Focus on tool metadata correctness, discovery failures, and policy/risk gaps.
Return concrete findings and actions in concise bullets.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
    max_turns=40,
    timeout_seconds=600,
    inactivity_timeout_seconds=120,
    retry_attempts=2,
)

INIT_INVESTIGATOR = SubagentDefinition(
    name="init_investigator",
    description="Fast-scan codebase investigator that generates AGENTS.md directly for /init command",
    goal_prompt="""You are an AGENTS.md generator for the /init command.

CRITICAL: Your ONLY task is to investigate the project and output the complete AGENTS.md content. Do NOT ask clarifying questions or defer to the user. Generate AGENTS.md based on what you discover.

INVESTIGATION WORKFLOW (scan quickly, max 10 turns):
1. Use list_dir and glob to understand directory structure
2. Read key config files to find:
   - Project name, description from pyproject.toml/package.json/README
   - Build/test/lint commands from scripts section
   - Dependencies and tech stack
3. Sample 2-3 source files to identify code patterns (imports, naming conventions, etc.)
4. Return the complete AGENTS.md file content

OUTPUT RULES:
- Start your response with "# AGENTS.md" as the first line
- Include these sections: Project Overview, Architecture, Development Guidelines, Configuration
- Be SPECIFIC: include actual file paths and commands you found
- Be CONCISE: aim for under 5KB; skip verbose examples
- Use markdown tables for tool preferences per file type
- If info is missing, omit the section rather than guess

EXAMPLE OUTPUT START:
# AGENTS.md

## Project Overview

**Project:** `actual_project_name`

Brief description based on README or package config.

## Architecture

```
src/
  package/
    __init__.py
    main.py
```

- Entry point: `src/package/main.py`
- Main package: `package`

## Development Guidelines

**Build Commands:**
| Command | Script |
|---------|--------|
| Build | `python -m build` |
| Test | `pytest` |

**Code Patterns:**
- Imports: `from __future__ import annotations`
- Constants: UPPER_CASE pattern

## Configuration

- Config: `pyproject.toml`
- Settings: `[tool.package]`

EXAMPLE OUTPUT END

Be fast. Output ONLY the AGENTS.md file content, starting with "# AGENTS.md".""",
    allowed_tools=["read_file", "glob", "list_dir"],
    max_turns=10,
    timeout_seconds=180,
    inactivity_timeout_seconds=60,
    retry_attempts=2,
)

VERIFICATION_REVIEWER = SubagentDefinition(
    name="verification_reviewer",
    description="Validates proposed or implemented changes with regression-focused verification guidance",
    goal_prompt="""You are a verification specialist.
Inspect changed areas and propose the most effective checks/tests to validate behavior.
Prioritize regression, safety, and acceptance criteria coverage.
Return concise findings and executable next actions.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "shell"],
    max_turns=12,
    timeout_seconds=360,
    inactivity_timeout_seconds=120,
    retry_attempts=1,
)


def get_default_subagent_definitions() -> list[SubagentDefinition]:
    return [
        CODEBASE_INVESTIGATOR,
        CODE_REVIEWER,
        TOOLING_GUARDIAN,
        INIT_INVESTIGATOR,
        VERIFICATION_REVIEWER,
    ]
