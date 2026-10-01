from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.subagent import INIT_INVESTIGATOR, SubagentTool


class ChildAgent:
    def __init__(self, config):
        self.session = SimpleNamespace(session_id="child")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def test_init_uses_configurable_budget_instead_of_specialist_defaults(tmp_path):
    async def work():
        config = Config(
            cwd=tmp_path,
            init_max_turns=60,
            init_timeout_seconds=10,
            mcp_servers={"unused": {"command": "unused-server"}},
            hooks_enabled=True,
        )
        definition = replace(INIT_INVESTIGATOR, timeout_seconds=0.001, retry_attempts=0)
        tool = SubagentTool(config, definition)

        async def runner(*, prompt, subagent_config, tool_calls, **kwargs):
            assert subagent_config.max_turns == 60
            assert subagent_config.mcp_servers == {}
            assert not subagent_config.hooks_enabled
            assert "grep" in subagent_config.allowed_tools
            await asyncio.sleep(0.01)  # Longer than the stale specialist timeout.
            return (
                "goal",
                '{"markdown":"# AGENTS.md\\n","inspected_files":[]}',
                None,
                "child",
                1,
            )

        tool._run_subagent_agent = runner
        with patch("ite.agent.agent.Agent", ChildAgent):
            result = await tool.execute(
                ToolInvocation(params={"goal": "Generate guidance"}, cwd=tmp_path)
            )
        assert result.success
        assert '"markdown"' in result.metadata["subagent_result"]["summary"]

    asyncio.run(work())


def test_cancelling_investigator_cancels_its_model_runner(tmp_path):
    async def work():
        tool = SubagentTool(Config(cwd=tmp_path), INIT_INVESTIGATOR)
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def runner(**kwargs):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                stopped.set()

        tool._run_subagent_agent = runner
        with patch("ite.agent.agent.Agent", ChildAgent):
            task = asyncio.create_task(
                tool.execute(
                    ToolInvocation(params={"goal": "Generate guidance"}, cwd=tmp_path)
                )
            )
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            result = await asyncio.gather(task, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert stopped.is_set()

    asyncio.run(work())


def test_revision_is_short_and_does_not_repeat_discovery(tmp_path):
    async def work():
        tool = SubagentTool(Config(cwd=tmp_path), INIT_INVESTIGATOR)

        async def runner(*, prompt, subagent_config, **kwargs):
            assert subagent_config.max_turns == 4
            assert subagent_config.allowed_tools == ["read_file"]
            assert "Do not repeat repository discovery" in prompt
            assert "COVERAGE:" not in prompt
            return "goal", "# AGENTS.md\nRevised", None, "child", 1

        tool._run_subagent_agent = runner
        with patch("ite.agent.agent.Agent", ChildAgent):
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "INIT_DRAFT_REVISION\nFix an unsupported command"},
                    cwd=tmp_path,
                )
            )
        assert result.success
        assert result.metadata["subagent_result"]["attempt_count"] == 1

    asyncio.run(work())


def test_successful_file_reads_are_recorded_from_agent_events(tmp_path):
    from ite.agent.events import AgentEvent
    from ite.tools.base import ToolResult

    class EventAgent(ChildAgent):
        async def run(self, prompt):
            yield AgentEvent.tool_call_start(
                "read-ok", "read_file", {"file_path": "README.md"}
            )
            yield AgentEvent.tool_call_complete(
                "read-ok", "read_file", ToolResult.success_result("contents")
            )
            yield AgentEvent.tool_call_start(
                "read-failed", "read_file", {"path": "missing.md"}
            )
            yield AgentEvent.tool_call_complete(
                "read-failed", "read_file", ToolResult.error_result("missing")
            )
            yield AgentEvent.text_complete("# AGENTS.md\nDocument")

    async def work():
        config = Config(cwd=tmp_path)
        agent = EventAgent(config)
        agent.session.turn_count = 1
        tool = SubagentTool(config, INIT_INVESTIGATOR)
        events = []

        async def record(event):
            events.append(event)

        await tool._run_subagent_agent(
            prompt="Generate",
            subagent_config=config,
            tool_calls=[],
            agent=agent,
            progress_callback=record,
        )
        assert [event["path"] for event in events if event["phase"] == "file_read"] == [
            "README.md"
        ]

    asyncio.run(work())
