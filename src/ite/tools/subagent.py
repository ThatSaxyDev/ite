import asyncio
import json
from dataclasses import dataclass
from typing import Any

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
        )


class SubagentTool(Tool):
    def __init__(
        self,
        config: Config,
        definition: SubagentDefinition,
    ):
        super().__init__(config)
        self.definition = definition

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
        # Treat subagents as non-mutating in plan mode when their tool allowlist
        # is strictly read-only. If allowlist is missing or includes mutating tools,
        # keep conservative behavior and mark as mutating.
        allowed = self.definition.allowed_tools
        if not allowed:
            return True

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

    async def _run_subagent_agent(
        self,
        *,
        prompt: str,
        subagent_config: Config,
        tool_calls: list[str],
    ) -> tuple[str, str | None, str | None]:
        from ite.agent.events import AgentEventType
        from ite.agent.agent import Agent

        final_response: str | None = None
        error: str | None = None
        terminate_response = "goal"

        async with Agent(subagent_config) as agent:
            async for event in agent.run(prompt):
                if event.type == AgentEventType.TOOL_CALL_START:
                    tool_calls.append(event.data.get("name"))
                elif event.type == AgentEventType.TEXT_COMPLETE:
                    final_response = event.data.get("content")
                elif event.type == AgentEventType.AGENT_END:
                    if final_response is None:
                        final_response = event.data.get("response")
                elif event.type == AgentEventType.AGENT_ERROR:
                    terminate_response = "error"
                    error = event.data.get("error", "Unknown error")
                    final_response = f"Sub-agent failed: {error}"
                    break

        return terminate_response, final_response, error

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = SubagentParams(**invocation.params)
        if not params.goal:
            return ToolResult.error_result("No goal specified for subagent")

        config_dict = self.config.to_dict()

        config_dict["max_turns"] = self.definition.max_turns

        if self.definition.allowed_tools:
            config_dict["allowed_tools"] = self.definition.allowed_tools

        subagent_config = Config(**config_dict)

        prompt = f"""You are a specialized sub-agent with a specific task to complete.

        {self.definition.goal_prompt}

        YOUR TASK:
        {params.goal}

        IMPORTANT:
        - Focus only on completing the specified task
        - Do not engage in unrelated actions
        - Once you have completed the task or have the answer, provide your final response
        - Be concise and direct in your output
        """

        tool_calls: list[str] = []
        final_response: str | None = None
        error: str | None = None
        terminate_response = "goal"

        try:
            terminate_response, final_response, error = await asyncio.wait_for(
                self._run_subagent_agent(
                    prompt=prompt,
                    subagent_config=subagent_config,
                    tool_calls=tool_calls,
                ),
                timeout=self.definition.timeout_seconds,
            )
        except asyncio.TimeoutError:
            terminate_response = "timeout"
            final_response = "Sub-agent timed out"
        except Exception as e:
            terminate_response = "error"
            error = str(e)
            final_response = f"Sub-agent failed: {e}"

        findings: list[str] = []
        actions: list[str] = []
        response_text = final_response or ""
        for line in response_text.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith(("finding:", "- finding:", "* finding:")):
                findings.append(stripped.split(":", 1)[-1].strip())
            if lower.startswith(("action:", "- action:", "* action:", "next:", "- next:")):
                actions.append(stripped.split(":", 1)[-1].strip())

        result_payload = {
            "status": "ok" if not error and terminate_response != "timeout" else "error",
            "subagent": self.definition.name,
            "termination": terminate_response,
            "tools_used": tool_calls,
            "summary": response_text or "No response",
            "findings": findings,
            "actions": actions,
        }

        output = json.dumps(result_payload, indent=2)
        metadata = {"subagent_result": result_payload}

        if error:
            return ToolResult.error_result(
                output=output,
                error=f"Sub-agent '{self.definition.name}' failed",
                metadata=metadata,
            )

        if terminate_response == "timeout":
            return ToolResult.error_result(
                output=output,
                error=f"Sub-agent '{self.definition.name}' timed out",
                metadata=metadata,
            )

        return ToolResult.success_result(output, metadata=metadata)


CODEBASE_INVESTIGATOR = SubagentDefinition(
    name="codebase_investigator",
    description="Investigates the codebase to answer questions about code structure, patterns, and implementations",
    goal_prompt="""You are a codebase investigation specialist.
Your job is to explore and understand code to answer questions.
Use read_file, grep, glob, and list_dir to investigate.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
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
    max_turns=10,
    timeout_seconds=300,
)

TOOLING_GUARDIAN = SubagentDefinition(
    name="tooling_guardian",
    description="Audits tool configuration, discovery health, and safety/routing integrity",
    goal_prompt="""You are a tooling integrity specialist.
Audit tool setup, safety boundaries, and runtime routing assumptions.
Focus on tool metadata correctness, discovery failures, and policy/risk gaps.
Return concrete findings and actions in concise bullets.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
    max_turns=30,
    timeout_seconds=300,
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
)


def get_default_subagent_definitions() -> list[SubagentDefinition]:
    return [
        CODEBASE_INVESTIGATOR,
        CODE_REVIEWER,
        TOOLING_GUARDIAN,
        VERIFICATION_REVIEWER,
    ]
