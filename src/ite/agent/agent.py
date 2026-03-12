from __future__ import annotations
import json
import uuid
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
import re


class Agent:
    PLAN_MIN_QUESTIONS = 3
    PLAN_MAX_QUESTIONS = 5
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

    async def run(self, message: str, user_model_content: str | list[dict] | None = None):
        session = self.session
        if session is None:
            yield AgentEvent.agent_error("Session is not available.")
            return

        await session.hook_system.trigger_before_agent(user_message=message)
        yield AgentEvent.agent_start(message)
        session.context_manager.add_user_message(message)
        is_execution_handoff = message.strip() == self.PLAN_EXECUTE_PROMPT
        session.todo_execution_handoff_active = is_execution_handoff
        if session.plan_mode_enabled and not is_execution_handoff:
            # Each new planning request starts a fresh question cycle.
            session.plan_questions_asked = 0
            session.plan_target_questions = self._determine_plan_question_target(
                message
            )
            session.set_plan_phase("asking_questions")
            async for seeded_event in self._seed_planning_todos_if_needed(session, message):
                yield seeded_event
        elif not session.plan_mode_enabled and not is_execution_handoff:
            async for seeded_event in self._seed_execution_todos_if_needed(session, message):
                yield seeded_event
        final_response: str | None = None

        try:
            async for event in self._agentic_loop(
                session,
                latest_user_text=message,
                latest_user_model_content=user_model_content,
            ):
                yield event

                if event.type == AgentEventType.TEXT_COMPLETE:
                    final_response = event.data.get("content")
        finally:
            session.todo_execution_handoff_active = False

        await session.hook_system.trigger_after_agent(
            user_message=message, agent_response=final_response
        )

        yield AgentEvent.agent_end(final_response)

    async def _seed_planning_todos_if_needed(
        self,
        session: Session,
        message: str,
    ) -> AsyncGenerator[AgentEvent, None]:
        state = session.export_todos_state()
        planning_items = state.get("planning", []) if isinstance(state, dict) else []
        if planning_items:
            return

        seed_items = self._derive_planning_seed_items(message)
        if not seed_items:
            return

        call_id = f"todos_seed_{uuid.uuid4().hex[:8]}"
        args = {
            "action": "add",
            "scope": "planning",
            "items": seed_items,
        }
        yield AgentEvent.tool_call_start(call_id, "todos", args)
        result = await session.tool_registry.invoke(
            "todos",
            args,
            self.config.cwd,
            session.hook_system,
            session.approval_manager,
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=session.plan_phase,
            todo_execution_handoff_active=session.todo_execution_handoff_active,
            set_plan_phase=session.set_plan_phase,
            plan_question_callback=self.plan_question_callback,
        )
        yield AgentEvent.tool_call_complete(call_id, "todos", result)
        if result.success:
            changed_ids = result.metadata.get("changed_ids", []) if isinstance(result.metadata, dict) else []
            if isinstance(changed_ids, list):
                session.planning_seed_ids = [str(i) for i in changed_ids if str(i).strip()]

    def _derive_planning_seed_items(self, message: str) -> list[str]:
        return [
            "Clarify requirements",
            "Define implementation approach",
            "Draft validation and testing strategy",
        ]

    async def _seed_execution_todos_if_needed(
        self,
        session: Session,
        message: str,
    ) -> AsyncGenerator[AgentEvent, None]:
        if not self._should_seed_execution_todos(message):
            return

        state = session.export_todos_state()
        execution_items = state.get("execution", []) if isinstance(state, dict) else []
        if execution_items:
            return

        seed_items = self._derive_execution_seed_items(message)
        if not seed_items:
            return

        call_id = f"todos_exec_seed_{uuid.uuid4().hex[:8]}"
        args = {"action": "add", "scope": "execution", "items": seed_items}
        yield AgentEvent.tool_call_start(call_id, "todos", args)
        result = await session.tool_registry.invoke(
            "todos",
            args,
            self.config.cwd,
            session.hook_system,
            session.approval_manager,
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=session.plan_phase,
            todo_execution_handoff_active=session.todo_execution_handoff_active,
            set_plan_phase=session.set_plan_phase,
            plan_question_callback=self.plan_question_callback,
        )
        yield AgentEvent.tool_call_complete(call_id, "todos", result)
        if result.success:
            changed_ids = result.metadata.get("changed_ids", []) if isinstance(result.metadata, dict) else []
            if isinstance(changed_ids, list):
                session.execution_seed_ids = [str(i) for i in changed_ids if str(i).strip()]

    def _should_seed_execution_todos(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if len(text) < 24:
            return False
        trivial_starts = ("what is", "show me", "where is", "explain", "summarize", "list ", "print ")
        if any(text.startswith(marker) for marker in trivial_starts):
            return False

        multi_step_markers = (
            "build",
            "implement",
            "create",
            "fix",
            "refactor",
            "add",
            "update",
            "migrate",
            " and ",
            " then ",
        )
        marker_hits = sum(1 for marker in multi_step_markers if marker in text)
        files_markers = (".py", ".ts", ".tsx", ".js", ".rs", ".go", "file", "files")
        has_files_hint = any(marker in text for marker in files_markers)
        return marker_hits >= 2 or (marker_hits >= 1 and has_files_hint)

    def _derive_execution_seed_items(self, message: str) -> list[str]:
        goal = (message or "").strip() or "user request"
        return [
            f"Implement requested changes for: {goal[:80]}",
            "Run verification checks (tests/lint/build as applicable)",
            "Summarize outcome and changed files",
        ]

    def _has_execution_todos(self, session: Session) -> bool:
        state = session.export_todos_state()
        execution = state.get("execution", []) if isinstance(state, dict) else []
        return bool(isinstance(execution, list) and execution)

    async def _complete_planning_seed_todo(
        self,
        session: Session,
        index: int,
    ) -> AsyncGenerator[AgentEvent, None]:
        todo_id = self._planning_seed_todo_id(session, index)
        if not todo_id:
            return
        if self._is_planning_todo_already_completed(session, todo_id):
            return

        call_id = f"todos_progress_{uuid.uuid4().hex[:8]}"
        args = {"action": "complete", "scope": "planning", "id": todo_id}
        yield AgentEvent.tool_call_start(call_id, "todos", args)
        result = await session.tool_registry.invoke(
            "todos",
            args,
            self.config.cwd,
            session.hook_system,
            session.approval_manager,
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=session.plan_phase,
            todo_execution_handoff_active=session.todo_execution_handoff_active,
            set_plan_phase=session.set_plan_phase,
            plan_question_callback=self.plan_question_callback,
        )
        yield AgentEvent.tool_call_complete(call_id, "todos", result)

    def _planning_seed_todo_id(self, session: Session, index: int) -> str | None:
        if 0 <= index < len(session.planning_seed_ids):
            return session.planning_seed_ids[index]

        state = session.export_todos_state()
        planning = state.get("planning", []) if isinstance(state, dict) else []
        if not isinstance(planning, list):
            return None
        if 0 <= index < len(planning):
            item = planning[index]
            if isinstance(item, dict):
                value = str(item.get("id", "")).strip()
                return value or None
        return None

    def _is_planning_todo_already_completed(self, session: Session, todo_id: str) -> bool:
        state = session.export_todos_state()
        planning = state.get("planning", []) if isinstance(state, dict) else []
        if not isinstance(planning, list):
            return False
        for item in planning:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "")).strip() != todo_id:
                continue
            return bool(item.get("completed", False))
        return False

    async def _complete_execution_seed_todo(
        self,
        session: Session,
        index: int,
    ) -> AsyncGenerator[AgentEvent, None]:
        todo_id = self._execution_seed_todo_id(session, index)
        if not todo_id:
            return
        if self._is_execution_todo_already_completed(session, todo_id):
            return

        call_id = f"todos_exec_progress_{uuid.uuid4().hex[:8]}"
        args = {"action": "complete", "scope": "execution", "id": todo_id}
        yield AgentEvent.tool_call_start(call_id, "todos", args)
        result = await session.tool_registry.invoke(
            "todos",
            args,
            self.config.cwd,
            session.hook_system,
            session.approval_manager,
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=session.plan_phase,
            todo_execution_handoff_active=session.todo_execution_handoff_active,
            set_plan_phase=session.set_plan_phase,
            plan_question_callback=self.plan_question_callback,
        )
        yield AgentEvent.tool_call_complete(call_id, "todos", result)

    def _execution_seed_todo_id(self, session: Session, index: int) -> str | None:
        if 0 <= index < len(session.execution_seed_ids):
            return session.execution_seed_ids[index]

        state = session.export_todos_state()
        execution = state.get("execution", []) if isinstance(state, dict) else []
        if not isinstance(execution, list):
            return None
        if 0 <= index < len(execution):
            item = execution[index]
            if isinstance(item, dict):
                value = str(item.get("id", "")).strip()
                return value or None
        return None

    def _is_execution_todo_already_completed(self, session: Session, todo_id: str) -> bool:
        state = session.export_todos_state()
        execution = state.get("execution", []) if isinstance(state, dict) else []
        if not isinstance(execution, list):
            return False
        for item in execution:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "")).strip() != todo_id:
                continue
            return bool(item.get("completed", False))
        return False

    def _is_verification_command(self, command: str) -> bool:
        cmd = (command or "").lower()
        if not cmd:
            return False
        markers = (
            " test",
            "pytest",
            "unittest",
            "vitest",
            "jest",
            "ruff",
            "mypy",
            "lint",
            " check",
            " build",
            "cargo test",
            "go test",
            "npm test",
            "pnpm test",
            "uv run pytest",
        )
        return any(marker in cmd for marker in markers)

    async def _auto_progress_execution_todos_on_tool(
        self,
        session: Session,
        *,
        tool_name: str,
        arguments: dict,
        success: bool,
    ) -> AsyncGenerator[AgentEvent, None]:
        if not success:
            return
        if tool_name == "todos":
            return

        if tool_name in {"write_file", "edit", "apply_patch"}:
            async for progress_event in self._complete_execution_seed_todo(session, 0):
                yield progress_event
            return

        if tool_name == "shell":
            command = str(arguments.get("command", "")).strip()
            if self._is_verification_command(command):
                async for progress_event in self._complete_execution_seed_todo(session, 1):
                    yield progress_event
                return
            # Non-verification shell work still counts as implementation progress.
            async for progress_event in self._complete_execution_seed_todo(session, 0):
                yield progress_event

    async def _agentic_loop(
        self,
        session: Session,
        *,
        latest_user_text: str,
        latest_user_model_content: str | list[dict] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        max_turns = self.config.max_turns

        for turn_num in range(max_turns):
            if self.session is not session:
                yield AgentEvent.agent_error("Session changed while turn was running.")
                return

            session.increment_turn()

            response_text = ""

            if session.context_manager.needs_compression():
                trigger_tokens = session.context_manager.estimate_current_context_tokens()
                context_window = self.config.model.context_window
                summary, usage = await session.chat_compactor.compact(
                    session.context_manager
                )

                if summary:
                    session.context_manager.replace_with_summary(summary)
                    compacted_tokens = (
                        session.context_manager.estimate_current_context_tokens()
                    )
                    # Reset latest context pressure to the compacted prompt size.
                    session.context_manager.set_latest_usage(
                        TokenUsage(
                            prompt_tokens=compacted_tokens,
                            completion_tokens=0,
                            total_tokens=compacted_tokens,
                            cached_tokens=0,
                        )
                    )
                    session.context_manager.add_usage(usage)
                    yield AgentEvent.context_compacted(
                        trigger_tokens=trigger_tokens,
                        context_window=context_window,
                        summary_chars=len(summary),
                    )

            tool_schemas = session.tool_registry.get_schemas()

            tool_calls: list[ToolCall] = []
            usage: TokenUsage | None = None
            stream_error: str | None = None

            outbound_messages = session.context_manager.get_messages()
            if latest_user_model_content is not None:
                for msg in reversed(outbound_messages):
                    if msg.get("role") == "user" and msg.get("content") == latest_user_text:
                        msg["content"] = latest_user_model_content
                        break

            async for event in session.client.chat_completion(
                outbound_messages,
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
                            session.plan_mode_enabled
                            and session.plan_phase != "executing"
                        ):
                            yield AgentEvent.text_delta(content)
                elif event.type == StreamEventType.TOOL_CALL_COMPLETE:
                    if event.tool_call:
                        tool_calls.append(event.tool_call)
                elif event.type == StreamEventType.ERROR:
                    stream_error = event.error or "Unknown error occurred"
                    yield AgentEvent.agent_error(stream_error)
                    break
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage

            if stream_error:
                # Fail this turn immediately instead of looping and repeating
                # the same upstream/provider error up to max_turns.
                return

            if session.plan_mode_enabled and session.plan_phase != "executing":
                # Deterministic planner UX: process at most one structured question per turn.
                plan_calls = [tc for tc in tool_calls if tc.name == "plan_question"]
                if len(plan_calls) > 1:
                    first_call = plan_calls[0]
                    non_plan_calls = [tc for tc in tool_calls if tc.name != "plan_question"]
                    tool_calls = non_plan_calls + [first_call]
                target_questions = max(
                    self.PLAN_MIN_QUESTIONS,
                    min(
                        self.PLAN_MAX_QUESTIONS,
                        int(getattr(session, "plan_target_questions", self.PLAN_MIN_QUESTIONS)),
                    ),
                )
                session.plan_target_questions = target_questions
                # Once enough questions are asked, transition to deterministic writing phase:
                # no extra tool calls should run before final plan output.
                if (
                    session.plan_questions_asked >= target_questions
                    and tool_calls
                ):
                    session.set_plan_phase("writing_plan")
                    session.context_manager.add_user_message(
                        "Question phase is complete. Do not call more tools now. "
                        "Write the final implementation plan directly with all required sections."
                    )
                    continue

            session.context_manager.add_assistant_message(
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
                    session.context_manager.set_latest_usage(usage)
                    session.context_manager.add_usage(usage)

                session.context_manager.prune_tool_outputs()
                if session.plan_mode_enabled:
                    if session.plan_phase != "executing":
                        target_questions = max(
                            self.PLAN_MIN_QUESTIONS,
                            min(
                                self.PLAN_MAX_QUESTIONS,
                                int(getattr(session, "plan_target_questions", self.PLAN_MIN_QUESTIONS)),
                            ),
                        )
                        if session.plan_questions_asked < target_questions:
                            remaining = target_questions - session.plan_questions_asked
                            session.set_plan_phase("asking_questions")
                            session.context_manager.add_user_message(
                                "Plan mode requirement: ask structured clarifying questions "
                                f"with the plan_question tool before finalizing the plan. "
                                f"Target {target_questions} total questions for this request; "
                                f"ask {remaining} more now."
                            )
                            continue
                        if not response_text.strip():
                            session.set_plan_phase("writing_plan")
                            session.context_manager.add_user_message(
                                "Now write the complete final implementation plan with the required "
                                "sections. Do not ask more questions in this turn."
                            )
                            continue
                        session.set_plan_phase(
                            "awaiting_implementation_confirmation"
                        )
                        plan_text = self._select_plan_text(session, response_text)
                        if plan_text.strip():
                            session.set_pending_plan(plan_text)
                            async for progress_event in self._complete_planning_seed_todo(session, 1):
                                yield progress_event
                            async for progress_event in self._complete_planning_seed_todo(session, 2):
                                yield progress_event
                            yield AgentEvent.text_complete(plan_text)
                            session.loop_detector.record_action(
                                "response", text=plan_text
                            )
                            yield AgentEvent.plan_ready(plan_text)
                    else:
                        if response_text:
                            async for progress_event in self._complete_execution_seed_todo(session, 2):
                                yield progress_event
                            yield AgentEvent.text_complete(response_text)
                            session.loop_detector.record_action(
                                "response", text=response_text
                            )
                        session.set_plan_phase("idle")
                elif response_text:
                    async for progress_event in self._complete_execution_seed_todo(session, 2):
                        yield progress_event
                    yield AgentEvent.text_complete(response_text)
                    session.loop_detector.record_action(
                        "response", text=response_text
                    )
                return

            if response_text:
                in_plan_questioning = (
                    session.plan_mode_enabled
                    and session.plan_phase != "executing"
                )
                if not in_plan_questioning:
                    yield AgentEvent.text_complete(response_text)
                session.loop_detector.record_action("response", text=response_text)

            tool_call_results: list[ToolResultMessage] = []
            skipped_plan_validation_errors: list[str] = []

            for tool_call in tool_calls:
                if (
                    session.plan_mode_enabled
                    and session.plan_phase != "executing"
                    and tool_call.name != "plan_question"
                ):
                    tool = session.tool_registry.get(tool_call.name)
                    if tool is not None:
                        validation_errors = tool.validate_params(tool_call.arguments)
                        if validation_errors:
                            skipped_plan_validation_errors.append(
                                f"{tool_call.name}: {'; '.join(validation_errors)}"
                            )
                            continue

                yield AgentEvent.tool_call_start(
                    tool_call.call_id,
                    tool_call.name,
                    tool_call.arguments,
                )

                session.loop_detector.record_action(
                    "tool_call",
                    tool_name=tool_call.name,
                    args=tool_call.arguments,
                )

                result = await session.tool_registry.invoke(
                    tool_call.name,
                    tool_call.arguments,
                    self.config.cwd,
                    session.hook_system,
                    session.approval_manager,
                    plan_mode_enabled=session.plan_mode_enabled,
                    plan_phase=session.plan_phase,
                    todo_execution_handoff_active=session.todo_execution_handoff_active,
                    set_plan_phase=session.set_plan_phase,
                    plan_question_callback=self.plan_question_callback,
                )

                if tool_call.name == "plan_question" and result.success:
                    session.increment_plan_questions()
                    session.set_plan_phase("writing_plan")
                    target_questions = max(
                        self.PLAN_MIN_QUESTIONS,
                        min(
                            self.PLAN_MAX_QUESTIONS,
                            int(getattr(session, "plan_target_questions", self.PLAN_MIN_QUESTIONS)),
                        ),
                    )
                    if session.plan_questions_asked >= target_questions:
                        async for progress_event in self._complete_planning_seed_todo(session, 0):
                            yield progress_event
                elif self._has_execution_todos(session):
                    async for progress_event in self._auto_progress_execution_todos_on_tool(
                        session,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        success=result.success,
                    ):
                        yield progress_event

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
                session.context_manager.add_tool_result(
                    tool_result.tool_call_id,
                    tool_result.content,
                )

            if skipped_plan_validation_errors:
                session.context_manager.add_user_message(
                    "The previous planning tool call had missing required parameters and was ignored: "
                    + " | ".join(skipped_plan_validation_errors)
                    + ". Retry with complete required arguments before continuing."
                )

            loop_message = session.loop_detector.check_for_loop()
            if loop_message:
                yield AgentEvent.loop_detected(loop_message)
                loop_breaker_prompt = create_loop_breaker_prompt(loop_message)
                session.context_manager.add_user_message(loop_breaker_prompt)

            if usage:
                session.context_manager.set_latest_usage(usage)
                session.context_manager.add_usage(usage)

            session.context_manager.prune_tool_outputs()

        yield AgentEvent.agent_error(f"Maximum turns ({max_turns}) reached")

    def _determine_plan_question_target(self, message: str) -> int:
        text = (message or "").strip().lower()
        if not text:
            return self.PLAN_MIN_QUESTIONS

        score = 0
        length = len(text)
        if length >= 120:
            score += 1
        if length >= 220:
            score += 1

        high_complexity_terms = (
            "architecture",
            "refactor",
            "migration",
            "rollout",
            "security",
            "auth",
            "multi-workspace",
            "backward-compatible",
            "integration",
            "end-to-end",
            "cross-platform",
            "persistence",
            "schema",
            "api",
            "performance",
            "test plan",
        )
        low_complexity_terms = ("quick", "small", "simple", "minor", "tiny")

        matches = sum(1 for term in high_complexity_terms if term in text)
        if matches >= 2:
            score += 1
        if matches >= 4:
            score += 1
        if any(term in text for term in low_complexity_terms):
            score -= 1

        target = self.PLAN_MIN_QUESTIONS + score
        return max(self.PLAN_MIN_QUESTIONS, min(self.PLAN_MAX_QUESTIONS, target))

    def _select_plan_text(self, session: Session, current_text: str) -> str:
        def _score(candidate: str) -> int:
            text = (candidate or "").strip()
            if not text:
                return -1
            lowered = text.lower()
            score = min(len(text) // 120, 60)
            markers = (
                "title",
                "summary",
                "implementation",
                "test",
                "assumption",
            )
            score += sum(5 for m in markers if m in lowered)
            if "implementation changes" in lowered:
                score += 20
            if "tests/validation" in lowered or "validation strategy" in lowered:
                score += 12
            if "assumptions/risks" in lowered or "assumptions & risks" in lowered:
                score += 10
            markdown_headers = re.findall(r"(?m)^#{1,3}\s+[^\n]+", text)
            score += min(len(markdown_headers) * 4, 40)
            if "i've created a comprehensive implementation plan" in lowered:
                score -= 20
            if "the plan includes" in lowered:
                score -= 20
            if "please review and let me know" in lowered:
                score -= 10
            return score

        candidates: list[str] = []
        if current_text and current_text.strip():
            candidates.append(current_text.strip())

        messages = session.context_manager.get_messages()
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if content in candidates:
                continue
            candidates.append(content)
            if len(candidates) >= 20:
                break

        if not candidates:
            return current_text

        best = max(candidates, key=lambda c: (_score(c), len(c)))
        return best

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
