from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import inspect
from typing import Any, Awaitable, Callable
from ite.config.config import ApprovalPolicy
from ite.tools.base import ToolConfirmation


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass
class ApprovalContext:

    tool_name: str
    params: dict[str, Any]
    is_mutating: bool
    affected_paths: list[Path]
    command: str | None = None
    is_dangerous: bool = False


DANGEROUS_PATTERNS = [
    # File system destruction
    r"rm\s+(-rf?|--recursive)\s+[/~]",
    r"rm\s+-rf?\s+\*",
    r"rmdir\s+[/~]",
    # Disk operations
    r"dd\s+if=",
    r"mkfs",
    r"fdisk",
    r"parted",
    # System control
    r"shutdown",
    r"reboot",
    r"halt",
    r"poweroff",
    r"init\s+[06]",
    # Permission changes on root
    r"chmod\s+(-R\s+)?777\s+[/~]",
    r"chown\s+-R\s+.*\s+[/~]",
    # Network exposure
    r"nc\s+-l",
    r"netcat\s+-l",
    # Code execution from network
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
    # Fork bomb
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
]

# Patterns for safe commands (can be auto-approved)
SAFE_PATTERNS = [
    # Information commands
    r"^(ls|dir|pwd|cd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(find|locate|which|whereis|file|stat)(\s|$)",
    # Development tools (read-only)
    r"^git\s+(status|log|diff|show|branch|remote|tag)(\s|$)",
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated)(\s|$)",
    r"^pip\s+(list|show|freeze)(\s|$)",
    r"^cargo\s+(tree|search)(\s|$)",
    # Text processing (usually safe)
    r"^(grep|awk|sed|cut|sort|uniq|tr|diff|comm)(\s|$)",
    # System info
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname)(\s|$)",
    r"^(env|printenv|set)$",
    # Process info
    r"^(ps|top|htop|pgrep)(\s|$)",
]

# Low-risk mutating tools that are safe to auto-approve in interactive policies.
LOW_RISK_MUTATING_TOOLS = {
    "todos",
}

# In on_request mode, allow low-risk file creation/overwrite inside cwd
# without prompting every time.
AUTO_APPROVE_ON_REQUEST_IN_CWD_TOOLS = {
    "write_file",
}


def _split_compound_command(command: str) -> list[str]:
    """Split a compound command into individual sub-commands.

    Handles: &&, ||, ;, and | (pipe)
    """
    # Split on &&, ||, ;, | — but not inside quotes
    parts = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    # Also handle $(...) subshells by extracting inner commands
    subshells = re.findall(r"\$\(([^)]+)\)", command)
    parts.extend(subshells)
    return [p.strip() for p in parts if p.strip()]


def is_dangerous_command(command: str) -> bool:
    """A compound command is dangerous if ANY sub-command is dangerous."""
    for sub_cmd in _split_compound_command(command):
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, sub_cmd, re.IGNORECASE):
                return True
    return False


def is_safe_command(command: str) -> bool:
    """A compound command is safe only if ALL sub-commands are safe."""
    sub_cmds = _split_compound_command(command)
    if not sub_cmds:
        return False

    for sub_cmd in sub_cmds:
        sub_is_safe = False
        for pattern in SAFE_PATTERNS:
            if re.search(pattern, sub_cmd, re.IGNORECASE):
                sub_is_safe = True
                break
        if not sub_is_safe:
            return False

    return True


class ApprovalManager:
    def __init__(
        self,
        approval_policy: ApprovalPolicy,
        cwd: Path,
        confirmation_callback: (
            Callable[[ToolConfirmation], bool | Awaitable[bool]] | None
        ) = None,
    ) -> None:
        self.approval_policy = approval_policy
        self.cwd = cwd
        self.confirmation_callback = confirmation_callback

    def _assess_command_safety(self, command: str) -> ApprovalDecision:
        if self.approval_policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if is_dangerous_command(command):
            return ApprovalDecision.REJECTED

        if self.approval_policy == ApprovalPolicy.NEVER:
            if is_safe_command(command):
                return ApprovalDecision.APPROVED
            return ApprovalDecision.REJECTED

        if self.approval_policy in {ApprovalPolicy.AUTO, ApprovalPolicy.ON_FAILURE}:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.AUTO_EDIT:
            if is_safe_command(command):
                return ApprovalDecision.APPROVED

            return ApprovalDecision.NEEDS_CONFIRMATION

        if is_safe_command(command):
            return ApprovalDecision.APPROVED

        return ApprovalDecision.NEEDS_CONFIRMATION

    async def check_approval(self, context: ApprovalContext) -> ApprovalDecision:
        if not context.is_mutating:
            return ApprovalDecision.APPROVED

        # Auto-approve low-risk in-session state updates, except under NEVER.
        if (
            context.tool_name in LOW_RISK_MUTATING_TOOLS
            and self.approval_policy != ApprovalPolicy.NEVER
        ):
            return ApprovalDecision.APPROVED

        if context.command:
            decision = self._assess_command_safety(context.command)
            return decision

        # Non-shell mutating operations (write_file, edit_file, etc.)
        # Check policy first
        if self.approval_policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.NEVER:
            return ApprovalDecision.REJECTED

        if self.approval_policy in {ApprovalPolicy.AUTO, ApprovalPolicy.ON_FAILURE}:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.AUTO_EDIT:
            # Auto-approve edits inside cwd, ask for outside
            for path in context.affected_paths:
                if not path.is_relative_to(self.cwd):
                    return ApprovalDecision.NEEDS_CONFIRMATION
            return ApprovalDecision.APPROVED

        if (
            self.approval_policy == ApprovalPolicy.ON_REQUEST
            and context.tool_name in AUTO_APPROVE_ON_REQUEST_IN_CWD_TOOLS
        ):
            for path in context.affected_paths:
                if not path.is_relative_to(self.cwd):
                    return ApprovalDecision.NEEDS_CONFIRMATION
            return ApprovalDecision.APPROVED

        # on_request: always ask for mutating operations
        if context.is_dangerous:
            return ApprovalDecision.NEEDS_CONFIRMATION

        return ApprovalDecision.NEEDS_CONFIRMATION

    async def request_confirmation(self, confirmation: ToolConfirmation) -> bool:
        if self.confirmation_callback:
            result = self.confirmation_callback(confirmation)
            if inspect.isawaitable(result):
                result = await result
            return result

        return True
