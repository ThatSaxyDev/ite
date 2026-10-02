from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from ite.config.config import Config, HookConfig, HookTrigger
from ite.tools.base import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class HookRun:
    id: str
    name: str
    trigger: str
    command: str
    cwd: str
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    duration_ms: int | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False
    tool_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "timed_out": self.timed_out,
            "tool_name": self.tool_name,
        }


class HookSystem:
    def __init__(self, config: Config):
        self.config = config
        self.hooks: list[HookConfig] = []
        if self.config.hooks_enabled:
            self.hooks = [hook for hook in self.config.hooks if hook.enabled]
        self._recent_runs: list[HookRun] = []
        self._max_recent_runs = 100
        self._background_tasks: set[asyncio.Task[HookRun]] = set()
        self.execution_suspended: Callable[[], bool] = lambda: False

    def is_suspended(self) -> bool:
        from ite.config.config import PermissionMode

        return self.execution_suspended() or self.config.permissions in {
            PermissionMode.ASK, PermissionMode.AUTOMATIC
        }

    def configured_hooks(self) -> list[dict[str, Any]]:
        return [
            {
                "name": hook.name,
                "trigger": hook.trigger.value,
                "command": hook.command or "<inline script>",
                "timeout_sec": hook.timeout_sec,
                "enabled": hook.enabled,
                "blocking": hook.blocking,
            }
            for hook in self.config.hooks
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.hooks_enabled),
            "suspended": self.is_suspended(),
            "configured": self.configured_hooks(),
            "runs": [run.to_dict() for run in self._recent_runs],
        }

    def _append_run(self, run: HookRun) -> None:
        self._recent_runs.append(run)
        if len(self._recent_runs) > self._max_recent_runs:
            self._recent_runs = self._recent_runs[-self._max_recent_runs :]

    def _create_run(self, hook: HookConfig, env: dict[str, str]) -> HookRun:
        command_label = hook.command or "<inline script>"
        run = HookRun(
            id=f"hook_{uuid.uuid4().hex[:10]}",
            name=hook.name,
            trigger=str(env.get("ITE_TRIGGER", hook.trigger.value)),
            command=command_label,
            cwd=str(self.config.cwd),
            tool_name=env.get("ITE_TOOL_NAME"),
        )
        self._append_run(run)
        return run

    async def _run_hook(
        self,
        hook: HookConfig,
        env: dict[str, str],
        run: HookRun | None = None,
    ) -> HookRun:
        run = run or self._create_run(hook, env)
        started = time.perf_counter()
        try:
            if hook.command:
                stdout, stderr, exit_code, timed_out = await self._run_command(
                    hook.command, hook.timeout_sec, env
                )
            else:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False
                ) as f:
                    f.write("#!/bin/bash\n")
                    f.write(hook.script or "")
                    script_path = f.name
                try:
                    os.chmod(script_path, 0o755)
                    stdout, stderr, exit_code, timed_out = await self._run_command(
                        script_path, hook.timeout_sec, env
                    )
                finally:
                    os.unlink(script_path)
            run.stdout = stdout
            run.stderr = stderr
            run.exit_code = exit_code
            run.timed_out = timed_out
            if timed_out:
                run.status = "timed_out"
                run.error = f"Timed out after {hook.timeout_sec:g}s"
            elif exit_code == 0:
                run.status = "completed"
            else:
                run.status = "failed"
                run.error = f"Exited with code {exit_code}"
        except asyncio.CancelledError:
            run.status = "cancelled"
            raise
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
            logger.exception("Hook %s failed", hook.name)
        finally:
            run.duration_ms = int((time.perf_counter() - started) * 1000)
        return run

    async def _dispatch_hook(self, hook: HookConfig, env: dict[str, str]) -> None:
        if self.is_suspended():
            return
        if hook.blocking:
            await self._run_hook(hook, env)
            return
        run = self._create_run(hook, env)
        task = asyncio.create_task(self._run_hook(hook, env, run))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    @property
    def has_running_hooks(self) -> bool:
        return any(run.status == "running" for run in self._recent_runs) or any(
            not task.done() for task in self._background_tasks
        )

    async def wait_for_background_hooks(self) -> None:
        if not self._background_tasks:
            return
        await asyncio.gather(*list(self._background_tasks), return_exceptions=True)

    async def _run_command(
        self,
        command: str,
        timeout: float,
        env: dict[str, str],
    ) -> tuple[str, str, int | None, bool]:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.cwd,
            env=env,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return (
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                process.returncode,
                False,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return ("", "", process.returncode, True)

    def _build_env(
        self,
        trigger: HookTrigger,
        tool_name: str | None = None,
        user_message: str | None = None,
        error: Exception | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env["ITE_TRIGGER"] = trigger.value
        env["ITE_CWD"] = str(self.config.cwd)

        if tool_name:
            env["ITE_TOOL_NAME"] = tool_name

        if user_message:
            env["ITE_USER_MESSAGE"] = user_message

        if error:
            env["ITE_ERROR"] = str(error)

        return env

    async def trigger_before_agent(self, user_message: str) -> None:
        env = self._build_env(
            HookTrigger.BEFORE_AGENT,
            user_message=user_message,
        )

        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_AGENT:
                await self._dispatch_hook(hook, env)

    async def trigger_after_agent(
        self,
        user_message: str,
        agent_response: str,
    ) -> None:
        env = self._build_env(
            HookTrigger.AFTER_AGENT,
            user_message=user_message,
        )
        env["ITE_RESPONSE"] = agent_response or ""

        for hook in self.hooks:
            if hook.trigger == HookTrigger.AFTER_AGENT:
                await self._dispatch_hook(hook, env)

    async def trigger_before_tool(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
    ) -> None:
        env = self._build_env(HookTrigger.BEFORE_TOOL, tool_name=tool_name)
        env["ITE_TOOL_PARAMS"] = json.dumps(tool_params)

        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_TOOL:
                await self._dispatch_hook(hook, env)

    async def trigger_after_tool(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        tool_result: ToolResult,
    ) -> None:
        env = self._build_env(HookTrigger.AFTER_TOOL, tool_name=tool_name)
        env["ITE_TOOL_PARAMS"] = json.dumps(tool_params)
        env["ITE_TOOL_RESULT"] = tool_result.to_model_output()

        for hook in self.hooks:
            if hook.trigger == HookTrigger.AFTER_TOOL:
                await self._dispatch_hook(hook, env)

    async def trigger_on_error(self, error: Exception) -> None:
        env = self._build_env(HookTrigger.ON_ERROR, error=error)

        for hook in self.hooks:
            if hook.trigger == HookTrigger.ON_ERROR:
                await self._dispatch_hook(hook, env)
