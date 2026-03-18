from ite.tools.base import ToolConfirmation
import signal
import asyncio
import sys
import fnmatch
import os
import re
from pathlib import Path
from pydantic import BaseModel, Field
from ite.tools.base import Tool, ToolKind, ToolInvocation, ToolResult
from ite.tools.base import ToolMetadata, ToolRiskLevel
from ite.safety.approval import classify_command_safety, CommandSafety
import shlex


_REDIRECT_OPERATORS = {">", ">>", "1>", "1>>", "2>", "2>>", "<", "<<", ">>>"}
_SHELL_COMMAND_WORDS = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "python",
    "python3",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "git",
    "ls",
    "cat",
    "echo",
    "pwd",
    "find",
    "grep",
    "sed",
    "awk",
    "make",
    "cargo",
    "pip",
    "pytest",
}


def _clean_shell_token(token: str) -> str:
    cleaned = token.strip().strip("'\"")
    if cleaned.startswith(("file://", "http://", "https://")):
        return ""
    return cleaned


def _extract_paths_from_command(command: str) -> list[Path]:
    """Extract likely filesystem paths from a shell command for sandbox validation."""
    paths: list[Path] = []
    seen: set[str] = set()
    home = Path.home()
    redirect_targets: list[str] = []

    for match in re.finditer(
        r"(?:(?:^|[\s;&|])(?:\d*>>?|\d*<)\s*)(\"[^\"]+\"|'[^']+'|[^\s;&|]+)",
        command,
    ):
        redirect_targets.append(match.group(1))

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = re.split(r"[\s;|&]+", command)

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token in _REDIRECT_OPERATORS and idx + 1 < len(tokens):
            redirect_targets.append(tokens[idx + 1])
            idx += 2
            continue
        idx += 1

    def add_path_token(raw: str) -> None:
        token = _clean_shell_token(raw)
        if not token:
            return
        if token.startswith("~"):
            token = token.replace("~", str(home), 1)

        looks_like_path = False
        if token.startswith("/"):
            looks_like_path = True
        elif token.startswith(".") and ("/" in token or token in {".", ".."}):
            looks_like_path = True
        elif ".." in token and "/" in token:
            looks_like_path = True
        elif "/" in token and not token.startswith("-"):
            looks_like_path = True

        if not looks_like_path:
            return

        normalized = token.rstrip(";,)")
        if normalized in seen:
            return
        seen.add(normalized)
        paths.append(Path(normalized))

    for token in tokens:
        cleaned = _clean_shell_token(token)
        if not cleaned or cleaned in _REDIRECT_OPERATORS:
            continue
        if cleaned.startswith("-"):
            continue
        if "=" in cleaned and "/" not in cleaned and not cleaned.startswith(("~", ".")):
            continue
        if cleaned in _SHELL_COMMAND_WORDS:
            continue
        add_path_token(cleaned)

    for token in redirect_targets:
        add_path_token(token)

    return paths


BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "mkfs",
    "fdisk",
    "parted",
    ":(){ :|:& };:",  # Fork bomb
    "chmod 777 /",
    "chmod -R 777",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
}


class ShellParams(BaseModel):
    command: str = Field(..., description="The shell command to execute")
    timeout: int = Field(
        120, ge=1, le=600, description="Timeout in seconds (default: 120)"
    )
    cwd: str | None = Field(None, description="Working directory for the command")


class ShellTool(Tool):
    name = "shell"
    kind = ToolKind.SHELL
    description = "Execute a shell command. Use this for running system commands, scripts and CLI tools."

    schema = ShellParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        command = str(params.get("command", "")).strip()
        return classify_command_safety(command) != CommandSafety.SAFE

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        command = str(params.get("command", "")).strip()
        safety = classify_command_safety(command)
        risk_level = {
            CommandSafety.SAFE: ToolRiskLevel.LOW,
            CommandSafety.CAUTION: ToolRiskLevel.MEDIUM,
            CommandSafety.DANGEROUS: ToolRiskLevel.HIGH,
        }[safety]
        return ToolMetadata(
            mutating=self.is_mutating(params),
            risk_level=risk_level,
            allowed_in_plan_mode=safety == CommandSafety.SAFE,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        params = ShellParams(**invocation.params)
        safety = classify_command_safety(params.command)

        for blocked in BLOCKED_COMMANDS:
            if blocked in params.command:
                return ToolConfirmation(
                    tool_name=self.name,
                    params=invocation.params,
                    description=f"Execute shell command (blocked as dangerous): {params.command}",
                    command=params.command,
                    is_dangerous=True,
                )

        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Execute shell command ({safety.value}): {params.command}",
            command=params.command,
            is_dangerous=safety == CommandSafety.DANGEROUS,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellParams(**invocation.params)
        safety = classify_command_safety(params.command)

        command = params.command.lower().strip()

        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                return ToolResult.error_result(
                    f"Command blocked for safety reasons: '{params.command}'",
                    metadata={
                        "blocked": True,
                        "safety_classification": safety.value,
                        "command": params.command,
                    },
                )

        if params.cwd:
            cwd = Path(params.cwd)
            if not cwd.is_absolute():
                cwd = invocation.cwd / cwd

        else:
            cwd = invocation.cwd

        if not cwd.exists():
            return ToolResult.error_result(f"Working directory does not exist: '{cwd}'")

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        # Also check paths referenced in the command itself
        for cmd_path in _extract_paths_from_command(params.command):
            resolved = (
                (cwd / cmd_path).resolve()
                if not cmd_path.is_absolute()
                else cmd_path.resolve()
            )
            path_error = self._sandbox_check(resolved, invocation.cwd)
            if path_error:
                return path_error

        env = self._build_environment()

        if sys.platform == "win32":
            shell_cmd = ["cmd.exe", "/c", params.command]
        else:
            shell_cmd = ["/bin/bash", "-c", params.command]

        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=params.timeout,
            )
        except asyncio.CancelledError:
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            raise
        except asyncio.TimeoutError:
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            return ToolResult.error_result(
                f"Command timed out after {params.timeout} seconds",
                metadata={
                    "command": params.command,
                    "cwd": str(cwd),
                    "timeout_seconds": params.timeout,
                    "timed_out": True,
                    "safety_classification": safety.value,
                },
            )

        stdout = stdout_data.decode("utf-8", errors="replace")
        stderr = stderr_data.decode("utf-8", errors="replace")

        exit_code = process.returncode

        output_parts: list[str] = []

        if stdout.strip():
            output_parts.append(stdout.rstrip())

        if stderr.strip():
            stderr_block = stderr.rstrip()
            if output_parts:
                output_parts.append("--- STDERR ---\n" + stderr_block)
            else:
                output_parts.append(stderr_block)

        output = "\n\n".join(output_parts)
        if exit_code != 0:
            output = (output + "\n\n" if output else "") + f"Exit code: {exit_code}"

        was_truncated = False
        if len(output) > 100 * 1024:
            output = output[: 100 * 1024] + "\n... [output truncated]"
            was_truncated = True

        return ToolResult(
            success=exit_code == 0,
            error=stderr if exit_code != 0 else None,
            exit_code=exit_code,
            output=output,
            truncated=was_truncated,
            metadata={
                "command": params.command,
                "cwd": str(cwd),
                "stdout_bytes": len(stdout_data),
                "stderr_bytes": len(stderr_data),
                "has_stdout": bool(stdout.strip()),
                "has_stderr": bool(stderr.strip()),
                "safety_classification": safety.value,
                "timed_out": False,
            },
        )

    def _build_environment(self) -> dict[str, str]:
        env = os.environ.copy()

        shell_environment = self.config.shell_environment

        if not shell_environment.ignore_default_excludes:
            for pattern in shell_environment.exclude_patterns:
                keys_to_remove = [
                    k for k in env.keys() if fnmatch.fnmatch(k.upper(), pattern.upper())
                ]

                for k in keys_to_remove:
                    del env[k]

        if shell_environment.set_vars:
            env.update(shell_environment.set_vars)

        return env
