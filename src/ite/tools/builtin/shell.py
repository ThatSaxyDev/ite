import asyncio
import fnmatch
import os
import re
import shutil
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
import shlex

from ite.safety.approval import CommandSafety, classify_command_safety
from ite.tools.base import ToolConfirmation
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from ite.tools.base import ToolMetadata, ToolRiskLevel


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

_SHELL_RUNNER_EXTRA_PATH_CANDIDATES = (
    "/Applications/Codex.app/Contents/Resources",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)
_SHELL_SESSION_BUFFER_LIMIT = 128 * 1024
_SHELL_SESSION_CHUNK_SIZE = 4096


@dataclass
class ShellSessionRecord:
    session_id: str
    process: asyncio.subprocess.Process
    command: str | None
    cwd: Path
    env: dict[str, str]
    created_at: float = field(default_factory=time.time)
    base_cursor: int = 0
    next_cursor: int = 0
    buffer: str = ""
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    last_activity_at: float = field(default_factory=time.time)
    exit_code: int | None = None
    stopped_by_tool: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    waiter_task: asyncio.Task[None] | None = None

    async def append(self, text: str, *, stream: str) -> None:
        if not text:
            return

        async with self.lock:
            payload = text
            if stream == "stderr":
                payload = f"\n--- STDERR ---\n{text}"

            self.buffer += payload
            self.next_cursor += len(payload)
            if stream == "stdout":
                self.stdout_bytes += len(text.encode("utf-8", errors="replace"))
            else:
                self.stderr_bytes += len(text.encode("utf-8", errors="replace"))
            self.last_activity_at = time.time()

            overflow = len(self.buffer) - _SHELL_SESSION_BUFFER_LIMIT
            if overflow > 0:
                self.buffer = self.buffer[overflow:]
                self.base_cursor += overflow

    async def snapshot(self, *, cursor: int, max_bytes: int) -> tuple[str, int, bool]:
        async with self.lock:
            normalized_cursor = max(cursor, self.base_cursor)
            start = normalized_cursor - self.base_cursor
            output = self.buffer[start:]
            encoded = output.encode("utf-8", errors="replace")
            truncated = False
            if len(encoded) > max_bytes:
                output = encoded[-max_bytes:].decode("utf-8", errors="replace")
                truncated = True
            return output, self.next_cursor, cursor < self.base_cursor or truncated


class ShellSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ShellSessionRecord] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        command: str | None,
        cwd: Path,
        env: dict[str, str],
    ) -> ShellSessionRecord:
        session_id = f"sh_{uuid.uuid4().hex[:12]}"
        if sys.platform == "win32":
            argv = ["cmd.exe", "/c", command] if command else ["cmd.exe"]
        elif command:
            argv = ["/bin/bash", "-lc", command]
        else:
            argv = ["/bin/bash"]

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        record = ShellSessionRecord(
            session_id=session_id,
            process=process,
            command=command,
            cwd=cwd,
            env=env,
        )
        record.reader_tasks = [
            asyncio.create_task(self._read_stream(record, process.stdout, "stdout")),
            asyncio.create_task(self._read_stream(record, process.stderr, "stderr")),
        ]
        record.waiter_task = asyncio.create_task(self._wait_for_exit(record))
        async with self._lock:
            self._sessions[session_id] = record
        return record

    async def get(self, session_id: str) -> ShellSessionRecord | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def send(self, session_id: str, text: str, *, append_newline: bool) -> ShellSessionRecord | None:
        record = await self.get(session_id)
        if record is None:
            return None
        if record.process.returncode is not None or record.process.stdin is None:
            return record

        payload = text + ("\n" if append_newline else "")
        try:
            record.process.stdin.write(payload.encode("utf-8"))
            await record.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await record.process.wait()
            record.exit_code = record.process.returncode
            return record
        record.last_activity_at = time.time()
        return record

    async def stop(self, session_id: str) -> ShellSessionRecord | None:
        record = await self.get(session_id)
        if record is None:
            return None
        record.stopped_by_tool = True
        await _terminate_process(record.process)
        async with self._lock:
            self._sessions.pop(session_id, None)
        return record

    async def shutdown(self) -> None:
        async with self._lock:
            records = list(self._sessions.values())
        for record in records:
            await self.stop(record.session_id)

    async def _read_stream(
        self,
        record: ShellSessionRecord,
        stream: asyncio.StreamReader | None,
        stream_name: str,
    ) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = await stream.read(_SHELL_SESSION_CHUNK_SIZE)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                await record.append(text, stream=stream_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _wait_for_exit(self, record: ShellSessionRecord) -> None:
        try:
            exit_code = await record.process.wait()
        except asyncio.CancelledError:
            raise
        record.exit_code = exit_code
        record.last_activity_at = time.time()


_SHELL_SESSION_MANAGER = ShellSessionManager()


def _terminate_process(process: asyncio.subprocess.Process) -> asyncio.Future[Any] | asyncio.Task[Any] | Any:
    async def _inner() -> None:
        if process.returncode is not None:
            return
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            await asyncio.wait_for(process.wait(), timeout=2)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    return _inner()


def _resolve_cwd(requested_cwd: str | None, invocation_cwd: Path) -> Path:
    if not requested_cwd:
        return invocation_cwd
    cwd = Path(requested_cwd)
    if not cwd.is_absolute():
        cwd = invocation_cwd / cwd
    return cwd


def _check_blocked_command(command: str, *, safety: CommandSafety) -> ToolResult | None:
    normalized = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in normalized:
            return ToolResult.error_result(
                f"Command blocked for safety reasons: '{command}'",
                metadata={
                    "blocked": True,
                    "safety_classification": safety.value,
                    "command": command,
                },
            )
    return None


class ShellParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    command: str = Field(
        ...,
        description="The shell command to execute",
        validation_alias=AliasChoices("command", "cmd", "script"),
    )
    timeout: int = Field(
        120, ge=1, le=600, description="Timeout in seconds (default: 120)"
    )
    cwd: str | None = Field(None, description="Working directory for the command")


class ShellStartParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    command: str | None = Field(
        None,
        description="Optional command to start in the session. Omit to start an interactive shell process.",
        validation_alias=AliasChoices("command", "cmd", "script"),
    )
    cwd: str | None = Field(None, description="Working directory for the command")


class ShellPollParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str = Field(
        ...,
        description="The shell session id returned by shell_start.",
        validation_alias=AliasChoices("session_id", "id"),
    )
    cursor: int = Field(
        0,
        ge=0,
        description="Read output since this cursor position. Use 0 on the first poll.",
    )
    max_bytes: int = Field(
        32 * 1024,
        ge=1,
        le=128 * 1024,
        description="Maximum amount of output to return.",
    )


class ShellSendParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str = Field(
        ...,
        description="The shell session id returned by shell_start.",
        validation_alias=AliasChoices("session_id", "id"),
    )
    input: str = Field(
        ...,
        description="Text to send to the running session stdin.",
        validation_alias=AliasChoices("input", "text", "chars"),
    )
    append_newline: bool = Field(
        True,
        description="Append a trailing newline to the provided input.",
    )


class ShellStopParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str = Field(
        ...,
        description="The shell session id returned by shell_start.",
        validation_alias=AliasChoices("session_id", "id"),
    )


class _ShellCommonTool(Tool):
    kind = ToolKind.SHELL

    def _resolve_and_validate_cwd(
        self,
        requested_cwd: str | None,
        invocation_cwd: Path,
    ) -> Path | ToolResult:
        cwd = _resolve_cwd(requested_cwd, invocation_cwd)
        if not cwd.exists():
            return ToolResult.error_result(f"Working directory does not exist: '{cwd}'")

        sandbox_error = self._sandbox_check(cwd, invocation_cwd)
        if sandbox_error:
            return sandbox_error
        return cwd

    def _validate_command_paths(
        self,
        *,
        command: str,
        cwd: Path,
        invocation_cwd: Path,
    ) -> ToolResult | None:
        for cmd_path in _extract_paths_from_command(command):
            resolved = (
                (cwd / cmd_path).resolve()
                if not cmd_path.is_absolute()
                else cmd_path.resolve()
            )
            path_error = self._sandbox_check(resolved, invocation_cwd)
            if path_error:
                return path_error
        return None

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

        discovered_rg = shutil.which("rg")
        candidate_dirs: list[str] = []
        if discovered_rg:
            candidate_dirs.append(str(Path(discovered_rg).resolve().parent))
        candidate_dirs.extend(_SHELL_RUNNER_EXTRA_PATH_CANDIDATES)

        existing_path = env.get("PATH", "")
        existing_parts = [part for part in existing_path.split(os.pathsep) if part]
        for candidate in candidate_dirs:
            if candidate and Path(candidate).exists() and candidate not in existing_parts:
                existing_parts.insert(0, candidate)
        if existing_parts:
            env["PATH"] = os.pathsep.join(existing_parts)

        return env


class ShellTool(_ShellCommonTool):
    name = "shell"
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

        blocked_error = _check_blocked_command(params.command, safety=safety)
        if blocked_error:
            return blocked_error

        cwd_result = self._resolve_and_validate_cwd(params.cwd, invocation.cwd)
        if isinstance(cwd_result, ToolResult):
            return cwd_result
        cwd = cwd_result

        path_error = self._validate_command_paths(
            command=params.command,
            cwd=cwd,
            invocation_cwd=invocation.cwd,
        )
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
                await _terminate_process(process)
            except ProcessLookupError:
                pass
            raise
        except asyncio.TimeoutError:
            try:
                await _terminate_process(process)
            except ProcessLookupError:
                pass
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


class ShellStartTool(_ShellCommonTool):
    name = "shell_start"
    description = "Start a persistent shell session or long-running command."
    schema = ShellStartParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        command = str(params.get("command", "")).strip()
        return classify_command_safety(command) != CommandSafety.SAFE if command else True

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        command = str(params.get("command", "")).strip()
        safety = classify_command_safety(command) if command else CommandSafety.CAUTION
        risk_level = {
            CommandSafety.SAFE: ToolRiskLevel.LOW,
            CommandSafety.CAUTION: ToolRiskLevel.MEDIUM,
            CommandSafety.DANGEROUS: ToolRiskLevel.HIGH,
        }[safety]
        return ToolMetadata(
            mutating=True,
            risk_level=risk_level,
            allowed_in_plan_mode=False,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        params = ShellStartParams(**invocation.params)
        description = (
            f"Start shell session: {params.command}"
            if params.command
            else "Start interactive shell session"
        )
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=description,
            command=params.command,
            is_dangerous=(
                classify_command_safety(params.command) == CommandSafety.DANGEROUS
                if params.command
                else False
            ),
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellStartParams(**invocation.params)
        if params.command:
            safety = classify_command_safety(params.command)
            blocked_error = _check_blocked_command(params.command, safety=safety)
            if blocked_error:
                return blocked_error
        cwd_result = self._resolve_and_validate_cwd(params.cwd, invocation.cwd)
        if isinstance(cwd_result, ToolResult):
            return cwd_result
        cwd = cwd_result

        if params.command:
            path_error = self._validate_command_paths(
                command=params.command,
                cwd=cwd,
                invocation_cwd=invocation.cwd,
            )
            if path_error:
                return path_error

        env = self._build_environment()
        record = await _SHELL_SESSION_MANAGER.start(
            command=params.command,
            cwd=cwd,
            env=env,
        )
        mode = "command" if params.command else "shell"
        started_message = (
            f"Started shell session `{record.session_id}` for `{params.command}`."
            if params.command
            else f"Started interactive shell session `{record.session_id}`."
        )
        return ToolResult.success_result(
            started_message,
            metadata={
                "session_id": record.session_id,
                "cwd": str(cwd),
                "mode": mode,
                "command": params.command,
                "cursor": 0,
                "running": True,
            },
        )


class ShellPollTool(_ShellCommonTool):
    name = "shell_poll"
    description = "Read incremental output and status from a running shell session."
    schema = ShellPollParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        return None

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellPollParams(**invocation.params)
        record = await _SHELL_SESSION_MANAGER.get(params.session_id)
        if record is None:
            return ToolResult.error_result(
                f"Shell session not found: '{params.session_id}'",
                metadata={"session_id": params.session_id, "missing_session": True},
            )

        output, next_cursor, history_truncated = await record.snapshot(
            cursor=params.cursor,
            max_bytes=params.max_bytes,
        )
        running = record.process.returncode is None
        status = "running" if running else "exited"
        message = output or f"No new output. Session `{params.session_id}` is {status}."
        return ToolResult.success_result(
            message,
            metadata={
                "session_id": params.session_id,
                "cursor": params.cursor,
                "next_cursor": next_cursor,
                "running": running,
                "status": status,
                "exit_code": record.exit_code,
                "cwd": str(record.cwd),
                "command": record.command,
                "stdout_bytes": record.stdout_bytes,
                "stderr_bytes": record.stderr_bytes,
                "history_truncated": history_truncated,
            },
        )


class ShellSendTool(_ShellCommonTool):
    name = "shell_send"
    description = "Send input to a running shell session."
    schema = ShellSendParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=False,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellSendParams(**invocation.params)
        record = await _SHELL_SESSION_MANAGER.send(
            params.session_id,
            params.input,
            append_newline=params.append_newline,
        )
        if record is None:
            return ToolResult.error_result(
                f"Shell session not found: '{params.session_id}'",
                metadata={"session_id": params.session_id, "missing_session": True},
            )
        if record.process.returncode is not None:
            return ToolResult.error_result(
                f"Shell session '{params.session_id}' is no longer running.",
                metadata={
                    "session_id": params.session_id,
                    "running": False,
                    "exit_code": record.exit_code,
                },
            )
        return ToolResult.success_result(
            f"Sent input to shell session `{params.session_id}`.",
            metadata={
                "session_id": params.session_id,
                "running": True,
                "append_newline": params.append_newline,
                "input_bytes": len(params.input.encode('utf-8')),
            },
        )


class ShellStopTool(_ShellCommonTool):
    name = "shell_stop"
    description = "Terminate a running shell session."
    schema = ShellStopParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=False,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellStopParams(**invocation.params)
        record = await _SHELL_SESSION_MANAGER.stop(params.session_id)
        if record is None:
            return ToolResult.error_result(
                f"Shell session not found: '{params.session_id}'",
                metadata={"session_id": params.session_id, "missing_session": True},
            )
        output, next_cursor, history_truncated = await record.snapshot(
            cursor=record.base_cursor,
            max_bytes=_SHELL_SESSION_BUFFER_LIMIT,
        )
        return ToolResult.success_result(
            output or f"Stopped shell session `{params.session_id}`.",
            metadata={
                "session_id": params.session_id,
                "running": False,
                "exit_code": record.exit_code,
                "next_cursor": next_cursor,
                "history_truncated": history_truncated,
                "cwd": str(record.cwd),
                "command": record.command,
            },
        )
