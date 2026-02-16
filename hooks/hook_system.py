import tempfile
import signal
import os
import sys
import asyncio
from config.config import HookTrigger
from config.config import HookConfig
from config.config import Config


class HookSystem:
    def __init__(self, config: Config):
        self.config = config
        self.hooks: list[HookConfig] = []

        if self.config.hooks_enabled:
            self.hooks = [hook for hook in self.config.hooks if hook.enabled]

    async def _run_hook(
        self,
        hook: HookConfig,
        env: dict[str, str],
    ) -> None:
        if hook.command:
            await self._run_command(hook.command, hook.timeout_sec, env)

        else:
            with tempfile.TemporaryDirectory(
                mode="w",
                suffix=".sh",
                delete=True,
            ) as f:
                f.write("#!/bin/bash\n")
                f.write(hook.script)
                script_path = f.name

            try:
                os.chmod(script_path, 0o755)
                self._run_command(script_path)
            finally:
                os.unlink(script_path)

    async def _run_command(
        self,
        command: str,
        timeout_sec: int,
        env: dict[str, str],
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.cwd,
            env=env,
            start_new_session=True,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            if sys.platform != "win32":
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
            await process.wait()

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
            env["ITE_ERROR"] = error

        return env

    async def trigger_before_agent(self, user_message: str) -> None:
        env = self._build_env(
            HookTrigger.BEFORE_AGENT,
            user_message=user_message,
        )
        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_AGENT:
                await self._run_hook(hook, env)

    async def trigger_after_agent(
        self,
        user_message: str,
        agent_response: str,
    ) -> None:
        env = self._build_env(
            HookTrigger.AFTER_AGENT,
            user_message=user_message,
        )
        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_AGENT:
                await self._run_hook(hook, env)
