from __future__ import annotations
import json
from ite.config.config import Config
from ite.client.response import ToolResultMessage
from ite.client.response import ToolCall
from ite.agent.events import AgentEventType
from ite.client.response import StreamEventType
from ite.agent.events import AgentEvent
from typing import AsyncGenerator
from ite.agent.session import Session
from ite.client.response import TokenUsage
from ite.tools.base import ToolConfirmation
from typing import Awaitable, Callable
from ite.prompts.system import create_loop_breaker_prompt


class Agent:
    PLAN_MIN_QUESTIONS = 2
    PLAN_EXECUTE_PROMPT = "Implement the approved plan now. Execute the planned changes."

    def __init__(
        self,
        config: Config,
        confirmation_callback: (
            Callable[[ToolConfirmation], bool | Awaitable[bool]] | None
        ) = None,
        plan_question_callback: (
            Callable[[dict], dict | Awaitable[dict]] | None
        ) = None,
    ):
        self.config = config
        self.session: Session | None = Session(self.config)
        self.session.approval_manager.confirmation_callback = confirmation_callback
        self.plan_question_callback = plan_question_callback

    async def run(self, message: str):
        await self.session.hook_system.trigger_before_agent(user_message=message)
        yield AgentEvent.agent_start(message)
        self.session.context_manager.add_user_message(message)
        is_execution_handoff = message.strip() == self.PLAN_EXECUTE_PROMPT
        if self.session.plan_mode_enabled and not is_execution_handoff:
            # Each new planning request starts a fresh question cycle.
            self.session.plan_questions_asked = 0
            self.session.set_plan_phase("asking_questions")
        final_response: str | None = None

        async for event in self._agentic_loop():
            yield event

            if event.type == AgentEventType.TEXT_COMPLETE:
                final_response = event.data.get("content")

        await self.session.hook_system.trigger_after_agent(
            user_message=message, agent_response=final_response
        )

        yield AgentEvent.agent_end(final_response)

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:
        max_turns = self.config.max_turns

        for turn_num in range(max_turns):
            self.session.increment_turn()

            response_text = ""

            if self.session.context_manager.needs_compression():
                trigger_tokens = self.session.context_manager.estimate_current_context_tokens()
                context_window = self.config.model.context_window
                summary, usage = await self.session.chat_compactor.compact(
                    self.session.context_manager
                )

                if summary:
                    self.session.context_manager.replace_with_summary(summary)
                    compacted_tokens = (
                        self.session.context_manager.estimate_current_context_tokens()
                    )
                    # Reset latest context pressure to the compacted prompt size.
                    self.session.context_manager.set_latest_usage(
                        TokenUsage(
                            prompt_tokens=compacted_tokens,
                            completion_tokens=0,
                            total_tokens=compacted_tokens,
                            cached_tokens=0,
                        )
                    )
                    self.session.context_manager.add_usage(usage)
                    yield AgentEvent.context_compacted(
                        trigger_tokens=trigger_tokens,
                        context_window=context_window,
                        summary_chars=len(summary),
                    )

            tool_schemas = self.session.tool_registry.get_schemas()

            tool_calls: list[ToolCall] = []
            usage: TokenUsage | None = None

            async for event in self.session.client.chat_completion(
                self.session.context_manager.get_messages(),
                tools=tool_schemas if tool_schemas else None,
                stream=True,
            ):
                if event.type == StreamEventType.TEXT_DELTA:
                    if event.text_delta:
                        content = event.text_delta.content
                        response_text += content
                        # In plan mode (pre-execution), suppress live text streaming.
                        # This prevents partial/final plan text from rendering before
                        # question flow is complete.
                        if not (
                            self.session.plan_mode_enabled
                            and self.session.plan_phase != "executing"
                        ):
                            yield AgentEvent.text_delta(content)
                elif event.type == StreamEventType.TOOL_CALL_COMPLETE:
                    if event.tool_call:
                        tool_calls.append(event.tool_call)
                elif event.type == StreamEventType.ERROR:
                    yield AgentEvent.agent_error(
                        event.error or "Unknown error occurred",
                    )
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage

            if self.session.plan_mode_enabled and self.session.plan_phase != "executing":
                # Deterministic planner UX: process at most one structured question per turn.
                plan_calls = [tc for tc in tool_calls if tc.name == "plan_question"]
                if len(plan_calls) > 1:
                    first_call = plan_calls[0]
                    non_plan_calls = [tc for tc in tool_calls if tc.name != "plan_question"]
                    tool_calls = non_plan_calls + [first_call]

            self.session.context_manager.add_assistant_message(
                response_text,
                [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ]
                if tool_calls
                else None,
            )

            if not tool_calls:
                if usage:
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)

                self.session.context_manager.prune_tool_outputs()
                if self.session.plan_mode_enabled:
                    if self.session.plan_phase != "executing":
                        if self.session.plan_questions_asked < self.PLAN_MIN_QUESTIONS:
                            remaining = self.PLAN_MIN_QUESTIONS - self.session.plan_questions_asked
                            self.session.set_plan_phase("asking_questions")
                            self.session.context_manager.add_user_message(
                                "Plan mode requirement: ask structured clarifying questions "
                                f"with the plan_question tool before finalizing the plan. "
                                f"At least {self.PLAN_MIN_QUESTIONS} total questions are required; "
                                f"ask {remaining} more now."
                            )
                            continue
                        if not response_text.strip():
                            self.session.set_plan_phase("writing_plan")
                            self.session.context_manager.add_user_message(
                                "Now write the complete final implementation plan with the required "
                                "sections. Do not ask more questions in this turn."
                            )
                            continue
                        self.session.set_plan_phase(
                            "awaiting_implementation_confirmation"
                        )
                        if response_text.strip():
                            yield AgentEvent.text_complete(response_text)
                            self.session.loop_detector.record_action(
                                "response", text=response_text
                            )
                            yield AgentEvent.plan_ready(response_text)
                    else:
                        if response_text:
                            yield AgentEvent.text_complete(response_text)
                            self.session.loop_detector.record_action(
                                "response", text=response_text
                            )
                        self.session.set_plan_phase("idle")
                elif response_text:
                    yield AgentEvent.text_complete(response_text)
                    self.session.loop_detector.record_action(
                        "response", text=response_text
                    )
                return

            if response_text:
                in_plan_questioning = (
                    self.session.plan_mode_enabled
                    and self.session.plan_phase != "executing"
                )
                if not in_plan_questioning:
                    yield AgentEvent.text_complete(response_text)
                self.session.loop_detector.record_action("response", text=response_text)

            tool_call_results: list[ToolResultMessage] = []

            for tool_call in tool_calls:
                yield AgentEvent.tool_call_start(
                    tool_call.call_id,
                    tool_call.name,
                    tool_call.arguments,
                )

                self.session.loop_detector.record_action(
                    "tool_call",
                    tool_name=tool_call.name,
                    args=tool_call.arguments,
                )

                result = await self.session.tool_registry.invoke(
                    tool_call.name,
                    tool_call.arguments,
                    self.config.cwd,
                    self.session.hook_system,
                    self.session.approval_manager,
                    plan_mode_enabled=self.session.plan_mode_enabled,
                    plan_phase=self.session.plan_phase,
                    set_plan_phase=self.session.set_plan_phase,
                    plan_question_callback=self.plan_question_callback,
                )

                if tool_call.name == "plan_question" and result.success:
                    self.session.increment_plan_questions()
                    self.session.set_plan_phase("writing_plan")

                yield AgentEvent.tool_call_complete(
                    tool_call.call_id,
                    tool_call.name,
                    result,
                )

                tool_call_results.append(
                    ToolResultMessage(
                        tool_call_id=tool_call.call_id,
                        content=result.to_model_output(),
                        is_error=not result.success,
                    )
                )

            for tool_result in tool_call_results:
                self.session.context_manager.add_tool_result(
                    tool_result.tool_call_id,
                    tool_result.content,
                )

            loop_message = self.session.loop_detector.check_for_loop()
            if loop_message:
                yield AgentEvent.loop_detected(loop_message)
                loop_breaker_prompt = create_loop_breaker_prompt(loop_message)
                self.session.context_manager.add_user_message(loop_breaker_prompt)

            if usage:
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

            self.session.context_manager.prune_tool_outputs()

        yield AgentEvent.agent_error(f"Maximum turns ({max_turns}) reached")

    async def __aenter__(self) -> Agent:
        await self.session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ) -> None:
        if self.session and self.session.client and self.session.mcp_manager:
            await self.session.client.close()
            await self.session.mcp_manager.shutdown()
            self.session = None
