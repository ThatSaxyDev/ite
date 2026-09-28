from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ite.tools.base import (
    Tool,
    ToolConfirmation,
    ToolInvocation,
    ToolKind,
    ToolMetadata,
    ToolResult,
    ToolRiskLevel,
)


class VerificationParams(BaseModel):
    command: str | None = Field(
        None,
        description="Optional explicit command to run instead of auto-detecting the project command.",
    )
    timeout: int = Field(
        300,
        ge=1,
        le=3600,
        description="Timeout in seconds for the verification command.",
    )


def _python_module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _package_manager(cwd: Path) -> str:
    package_json = _read_json_file(cwd / "package.json") or {}
    package_manager = str(package_json.get("packageManager", "")).strip().lower()
    if package_manager.startswith("pnpm"):
        return "pnpm"
    if package_manager.startswith("yarn"):
        return "yarn"
    if (cwd / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (cwd / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _npm_script_command(cwd: Path, script_name: str) -> str | None:
    package_json = _read_json_file(cwd / "package.json") or {}
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return None
    if script_name not in scripts:
        return None
    manager = _package_manager(cwd)
    if manager == "yarn":
        return f"yarn {script_name}"
    return f"{manager} run {script_name}"


def _detect_test_command(cwd: Path) -> str | None:
    for script_name in ("test", "test:unit"):
        command = _npm_script_command(cwd, script_name)
        if command:
            return command

    tests_dir = cwd / "tests"
    if tests_dir.is_dir():
        return "python3 -m unittest discover -s tests"
    if _python_module_available("pytest") and any(
        (cwd / name).exists() for name in ("pytest.ini", "conftest.py")
    ):
        return "python3 -m pytest"
    return None


def _detect_lint_command(cwd: Path) -> str | None:
    for script_name in ("lint", "check"):
        command = _npm_script_command(cwd, script_name)
        if command:
            return command

    if _python_module_available("ruff"):
        return "python3 -m ruff check ."
    if _python_module_available("flake8"):
        return "python3 -m flake8 ."
    return None


def _detect_typecheck_command(cwd: Path) -> str | None:
    for script_name in ("typecheck", "check-types", "types"):
        command = _npm_script_command(cwd, script_name)
        if command:
            return command

    if _python_module_available("mypy"):
        return "python3 -m mypy ."

    local_tsc = cwd / "node_modules" / ".bin" / "tsc"
    if local_tsc.exists():
        return f"{local_tsc} --noEmit"
    if (cwd / "tsconfig.json").exists() and shutil.which("tsc"):
        return "tsc --noEmit"
    return None


async def _run_command(command: str, *, cwd: Path, timeout: int) -> tuple[int | None, str, str, bool]:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable="/bin/bash",
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return process.returncode, stdout, stderr, timed_out


def _compose_output(stdout: str, stderr: str) -> str:
    stdout = stdout.strip()
    stderr = stderr.strip()
    if stdout and stderr:
        return f"{stdout}\n\n--- STDERR ---\n{stderr}"
    return stdout or stderr


def _summarize_test_output(output: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    unittest_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", output)
    if unittest_match:
        summary["tests_ran"] = int(unittest_match.group(1))
        summary["duration_seconds"] = float(unittest_match.group(2))
        summary["framework"] = "unittest"
    pytest_match = re.search(r"=+\s+(.+?)\s+in\s+([0-9.]+)s\s+=+", output)
    if pytest_match and "framework" not in summary:
        summary["framework"] = "pytest"
        summary["pytest_summary"] = pytest_match.group(1).strip()
        summary["duration_seconds"] = float(pytest_match.group(2))
    return summary


def _detect_missing_dependency(command: str, output: str) -> dict[str, Any]:
    text = output or ""
    lowered = text.lower()
    metadata: dict[str, Any] = {}

    module_match = re.search(r"No module named ([A-Za-z0-9_.-]+)", text)
    if module_match:
        missing = module_match.group(1)
        metadata.update(
            {
                "missing_dependency": True,
                "missing_dependency_kind": "python_module",
                "missing_dependency_name": missing,
                "recoverable": True,
                "recovery_hint": (
                    f"{missing} is not installed for `{command}`. Ask the user before installing it."
                ),
            }
        )
        return metadata

    command_not_found = re.search(r"(command not found|not recognized as an internal or external command)", lowered)
    if command_not_found:
        first_token = command.strip().split()[0] if command.strip() else ""
        metadata.update(
            {
                "missing_dependency": True,
                "missing_dependency_kind": "command",
                "missing_dependency_name": first_token,
                "recoverable": True,
                "recovery_hint": (
                    f"`{first_token}` is unavailable for `{command}`. Ask the user before installing tooling."
                ),
            }
        )
        return metadata

    return metadata


class _VerificationTool(Tool):
    command_kind: str = ""

    schema = VerificationParams
    kind = ToolKind.SHELL

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.MEDIUM,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = VerificationParams(**invocation.params)
        command = (params.command or "").strip() or f"auto-detect {self.command_kind} command"
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Run {self.command_kind} command: {command}",
            params=invocation.params,
            affected_paths=[invocation.cwd.resolve()],
        )

    def _detect_command(self, cwd: Path) -> str | None:
        raise NotImplementedError

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = VerificationParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        command = (params.command or "").strip() or self._detect_command(cwd)
        if not command:
            return ToolResult.error_result(
                f"Unable to determine a {self.command_kind} command for this workspace. Provide `command` explicitly.",
                metadata={"command_kind": self.command_kind},
            )

        started = time.perf_counter()
        exit_code, stdout, stderr, timed_out = await _run_command(
            command,
            cwd=cwd,
            timeout=params.timeout,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        output = _compose_output(stdout, stderr)
        metadata: dict[str, Any] = {
            "command": command,
            "cwd": str(cwd),
            "timeout": params.timeout,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "command_kind": self.command_kind,
        }
        if self.command_kind == "tests":
            metadata.update(_summarize_test_output(output))
        metadata.update(_detect_missing_dependency(command, output))

        if timed_out:
            return ToolResult.error_result(
                f"{self.command_kind.capitalize()} command timed out after {params.timeout}s.",
                output=output,
                metadata=metadata,
                exit_code=exit_code,
            )
        if exit_code != 0:
            return ToolResult.error_result(
                f"{self.command_kind.capitalize()} command failed with exit code {exit_code}.",
                output=output,
                metadata=metadata,
                exit_code=exit_code,
            )
        return ToolResult.success_result(
            output or f"{self.command_kind.capitalize()} command completed successfully.",
            metadata=metadata,
            exit_code=exit_code,
        )


class RunTestsTool(_VerificationTool):
    name = "run_tests"
    description = "Run the project's test command, or a provided test command override."
    command_kind = "tests"

    def _detect_command(self, cwd: Path) -> str | None:
        return _detect_test_command(cwd)


class RunLinterTool(_VerificationTool):
    name = "run_linter"
    description = "Run the project's linter command, or a provided linter command override."
    command_kind = "linter"

    def _detect_command(self, cwd: Path) -> str | None:
        return _detect_lint_command(cwd)


class RunTypecheckTool(_VerificationTool):
    name = "run_typecheck"
    description = "Run the project's typecheck command, or a provided typecheck command override."
    command_kind = "typecheck"

    def _detect_command(self, cwd: Path) -> str | None:
        return _detect_typecheck_command(cwd)
