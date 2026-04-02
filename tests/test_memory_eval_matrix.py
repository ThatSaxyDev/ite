import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config


@dataclass
class EvalTurnResult:
    response: str
    system_prompt: str


class _EvalModel:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    async def chat_completion(self, messages, tools=None, stream=True):
        system_prompt = "\n\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        self.system_prompts.append(system_prompt)

        latest_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                latest_user = str(msg.get("content", ""))
                break

        response = self._select_response(system_prompt, latest_user)
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(response),
        )
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    def _select_response(self, system_prompt: str, latest_user: str) -> str:
        prompt = system_prompt.lower()
        user = latest_user.lower()

        if "what language switch am i considering?" in user:
            return (
                "You are considering switching to Go."
                if "switching to go" in prompt
                else "No remembered language switch."
            )

        if "what have we decided about storage?" in user:
            return (
                "We decided to use Redis."
                if "redis" in prompt
                else "No storage decision recorded."
            )

        if "how should you answer architecture questions by default?" in user:
            return (
                "Architecture questions should get more detail."
                if "give detailed answers by default." in prompt
                else "No durable architecture-specific preference is stored."
            )

        if "what phrase should you remember for this session only?" in user:
            return (
                "The phrase is mango submarine velvet."
                if "mango submarine velvet" in prompt
                else "No session phrase stored."
            )

        if "what test tool should we use here?" in user:
            return (
                "Use pytest for tests."
                if "pytest" in prompt
                else "No workspace testing memory stored."
            )

        if "we have a failing auth test. what should i check first?" in user:
            return (
                "Short answer: check the failing assertion and auth setup."
                if "keep answers short by default." in prompt
                else "Detailed answer: inspect auth setup in detail."
            )

        if "explain the architecture of this repo." in user:
            return (
                "Detailed answer:\n- sessions\n- tools\n- context"
                if "give detailed answers by default." in prompt
                else "Short answer: session, tools, context."
            )

        if "explain what this codebase is about extensively." in user:
            return (
                "Detailed answer: this codebase is a terminal coding agent with sessions, tools, memory, and UI layers."
                if "give detailed answers by default." in prompt
                else "Short answer: it is a terminal coding agent."
            )

        if "explain what this codebase is about properly." in user:
            return (
                "Detailed answer: this codebase is a terminal coding agent with orchestration, tools, memory, prompts, and UI layers."
                if "give detailed answers by default." in prompt
                else "Short answer: it is a terminal coding agent."
            )

        if "what is 17 times 19?" in user:
            return "323"

        if "do not remember this" in user:
            return "Okay, I will not store that."

        if "remember" in user or "from now on" in user:
            return "Stored."

        return "No relevant memory."


class MemoryEvalMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        patcher = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_eval_matrix(self) -> None:
        await self._scenario_session_isolation()
        await self._scenario_exact_session_recall()
        await self._scenario_workspace_persistence()
        await self._scenario_long_term_preference()
        await self._scenario_current_request_can_override_short_preference()
        await self._scenario_semantic_request_wording_can_override_short_preference()
        await self._scenario_preference_update()
        await self._scenario_irrelevant_recall_restraint()
        await self._scenario_do_not_remember_opt_out()
        await self._scenario_speculative_statement_not_captured()
        await self._scenario_conditional_preferences_apply_by_context()

    async def _scenario_session_isolation(self) -> None:
        workspace = self.base_path / "session-isolation"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "For this session only, remember the phrase: mango submarine velvet.")
        same = await self._run_turn(agent, "What phrase should you remember for this session only?")
        self.assertIn("mango submarine velvet", same.response.lower())

        fresh, _ = await self._make_agent(workspace)
        isolated = await self._run_turn(fresh, "What phrase should you remember for this session only?")
        self.assertIn("no session phrase stored", isolated.response.lower())

    async def _scenario_workspace_persistence(self) -> None:
        workspace_a = self.base_path / "workspace-a"
        workspace_b = self.base_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        agent_a, _ = await self._make_agent(workspace_a)
        await self._run_turn(agent_a, "Remember this for this workspace: use pytest for tests.")

        same_workspace, _ = await self._make_agent(workspace_a)
        same = await self._run_turn(same_workspace, "What test tool should we use here?")
        self.assertIn("pytest", same.response.lower())
        self.assertEqual(same.system_prompt, same_workspace.session.context_manager.get_messages()[0]["content"])

        other_workspace, _ = await self._make_agent(workspace_b)
        other = await self._run_turn(other_workspace, "What test tool should we use here?")
        self.assertIn("no workspace testing memory stored", other.response.lower())

    async def _scenario_exact_session_recall(self) -> None:
        workspace = self.base_path / "exact-session-recall"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "For this session only, remember the phrase: mango submarine velvet.")

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("LLM should not be called for exact session recall")
            yield  # pragma: no cover

        assert agent.session is not None
        agent.session.client.chat_completion = fail_if_called  # type: ignore[method-assign]
        result = await self._run_turn(agent, "What phrase should you remember for this session only?")
        self.assertEqual(result.response.strip(), "mango submarine velvet")

    async def _scenario_long_term_preference(self) -> None:
        workspace = self.base_path / "long-term"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "From now on, keep answers short and avoid bullet lists.")

        fresh, _ = await self._make_agent(workspace)
        result = await self._run_turn(fresh, "Explain the architecture of this repo.")
        self.assertIn("short answer", result.response.lower())
        self.assertIn("keep answers short by default.", result.system_prompt.lower())
        self.assertIn(
            "avoid bullet lists unless the user explicitly asks for them.",
            result.system_prompt.lower(),
        )

    async def _scenario_preference_update(self) -> None:
        workspace = self.base_path / "preference-update"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "From now on, keep answers short and avoid bullet lists.")
        await self._run_turn(
            agent,
            "From now on, give detailed answers with bullet lists when helpful.",
        )

        fresh, _ = await self._make_agent(workspace)
        result = await self._run_turn(fresh, "Explain the architecture of this repo.")
        self.assertIn("detailed answer", result.response.lower())
        self.assertIn("sessions", result.response.lower())
        self.assertIn("give detailed answers by default.", result.system_prompt.lower())
        self.assertIn("use bullet lists when they materially improve clarity.", result.system_prompt.lower())
        self.assertNotIn("keep answers short by default.", result.system_prompt.lower())

    async def _scenario_current_request_can_override_short_preference(self) -> None:
        workspace = self.base_path / "request-override"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "From now on, keep answers short and avoid bullet lists.")

        result = await self._run_turn(agent, "Explain what this codebase is about extensively.")
        self.assertIn("detailed answer", result.response.lower())
        self.assertIn("give detailed answers by default.", result.system_prompt.lower())

    async def _scenario_semantic_request_wording_can_override_short_preference(self) -> None:
        workspace = self.base_path / "semantic-request-override"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "From now on, keep answers short and avoid bullet lists.")

        result = await self._run_turn(agent, "Explain what this codebase is about properly.")
        self.assertIn("detailed answer", result.response.lower())
        self.assertIn("give detailed answers by default.", result.system_prompt.lower())

    async def _scenario_irrelevant_recall_restraint(self) -> None:
        workspace = self.base_path / "restraint"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "Remember this for this workspace: use pytest for tests.")
        await self._run_turn(agent, "For this session only, remember the phrase: mango submarine velvet.")

        result = await self._run_turn(agent, "What is 17 times 19?")
        self.assertEqual(result.response.strip(), "323")
        self.assertNotIn("mango submarine velvet", result.system_prompt.lower())
        self.assertNotIn("pytest", result.system_prompt.lower())

    async def _scenario_do_not_remember_opt_out(self) -> None:
        workspace = self.base_path / "do-not-remember"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(agent, "Do not remember this: I am considering switching to Go.")

        fresh, _ = await self._make_agent(workspace)
        result = await self._run_turn(fresh, "What language switch am I considering?")
        self.assertIn("no remembered language switch", result.response.lower())
        self.assertNotIn("switching to go", result.system_prompt.lower())

    async def _scenario_speculative_statement_not_captured(self) -> None:
        workspace = self.base_path / "speculative"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(
            agent,
            "I'm just thinking out loud, maybe we could use Redis, or maybe not.",
        )

        fresh, _ = await self._make_agent(workspace)
        result = await self._run_turn(fresh, "What have we decided about storage?")
        self.assertIn("no storage decision recorded", result.response.lower())
        self.assertNotIn("redis", result.system_prompt.lower())

    async def _scenario_conditional_preferences_apply_by_context(self) -> None:
        workspace = self.base_path / "conditional-preference"
        workspace.mkdir()

        agent, _ = await self._make_agent(workspace)
        await self._run_turn(
            agent,
            "Remember this preference: for debugging, keep answers short; for architecture, give detailed answers.",
        )

        debug_result = await self._run_turn(
            agent,
            "We have a failing auth test. What should I check first?",
        )
        architecture_result = await self._run_turn(
            agent,
            "Explain the architecture of this repo.",
        )
        self.assertIn("short answer", debug_result.response.lower())
        self.assertIn("keep answers short by default.", debug_result.system_prompt.lower())
        self.assertIn("debugging", debug_result.system_prompt.lower())
        self.assertIn("detailed answer", architecture_result.response.lower())
        self.assertIn("give detailed answers by default.", architecture_result.system_prompt.lower())
        self.assertIn("architecture", architecture_result.system_prompt.lower())

    async def _make_agent(self, workspace: Path) -> tuple[Agent, _EvalModel]:
        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        model = _EvalModel()
        agent.session.client.chat_completion = model.chat_completion  # type: ignore[method-assign]
        return agent, model

    async def _run_turn(self, agent: Agent, message: str) -> EvalTurnResult:
        response = ""
        async for event in agent.run(message):
            if event.type == AgentEventType.TEXT_COMPLETE:
                response = event.data.get("content", "")
        assert agent.session is not None
        system_prompt = agent.session.context_manager.get_messages()[0]["content"]
        return EvalTurnResult(response=response, system_prompt=system_prompt)


if __name__ == "__main__":
    unittest.main()
