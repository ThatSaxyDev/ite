from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator, Awaitable, Callable

from ite.agent.change_history import file_diffs_from_tool_result
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.client.response import StreamEventType, TokenUsage, ToolCall, ToolResultMessage
from ite.config.config import Config
from ite.memory import (
    parse_exact_recall_probe,
    parse_explicit_memory_instruction,
    parse_explicit_memory_instructions,
    resolve_response_intent,
)
from ite.prompts.system import create_loop_breaker_prompt
from ite.tools.base import ToolConfirmation, ToolResult
from ite.utils.paths import resolve_path
from ite.utils.errors import is_context_overflow_error


class Agent:
    PLAN_MIN_QUESTIONS = 3
    PLAN_MAX_QUESTIONS = 5
    PLAN_EXECUTE_PROMPT = (
        "Implement the approved plan now. Execute the planned changes."
    )
    POST_COMPACTION_CONTINUATION_DELAY_SECONDS = 1.25
    POST_COMPACTION_MAX_RECOVERY_RETRIES = 2
    INCOMPLETE_RESPONSE_MAX_RETRIES = 1
    POST_COMPACTION_CONTINUE_PROMPT = (
        "Continue from the compacted context and finish the current task. "
        "Treat compaction as a boundary, not a failure. "
        "Use any preserved tool results or recent messages, do not repeat completed work, "
        "and continue with the next concrete step."
    )
    RAW_TOOL_CALL_OPEN_MARKERS = (
        "<|tool_call|>",
        "<tool_call|>",
        "<|tool_call>",
        "<tool_call>",
    )
    RAW_TOOL_CALL_CLOSE_MARKERS = (
        "<|tool_call|>",
        "<tool_call|>",
        "<|tool_call>",
        "</tool_call|>",
        "</tool_call>",
        "<|/tool_call|>",
    )
    DUPLICATE_DISCOVERY_TOOL_NAMES = {"list_dir", "glob", "grep", "read_file"}

    def __init__(
        self,
        config: Config,
        session: Session | None = None,
        confirmation_callback: (
            Callable[[ToolConfirmation], bool | Awaitable[bool]] | None
        ) = None,
        plan_question_callback: (
            Callable[[dict], dict | Awaitable[dict]] | None
        ) = None,
    ):
        self.config = config
        self.session: Session | None = session or Session(self.config)
        self.session.approval_manager.confirmation_callback = confirmation_callback
        self.plan_question_callback = plan_question_callback

    @classmethod
    def _raw_tool_call_markers(cls) -> tuple[str, ...]:
        return cls.RAW_TOOL_CALL_OPEN_MARKERS + tuple(
            marker
            for marker in cls.RAW_TOOL_CALL_CLOSE_MARKERS
            if marker not in cls.RAW_TOOL_CALL_OPEN_MARKERS
        )

    @classmethod
    def _longest_partial_tool_marker_suffix(cls, value: str) -> int:
        longest = 0
        for marker in cls._raw_tool_call_markers():
            max_prefix = min(len(marker) - 1, len(value))
            for prefix_len in range(max_prefix, 0, -1):
                if value.endswith(marker[:prefix_len]):
                    longest = max(longest, prefix_len)
                    break
        return longest

    @classmethod
    def _consume_raw_tool_call_markup(
        cls,
        text: str,
        *,
        inside_markup: bool,
        final: bool = False,
    ) -> tuple[str, str, bool]:
        if not text:
            return "", "", inside_markup

        visible_parts: list[str] = []
        index = 0
        open_markers = cls.RAW_TOOL_CALL_OPEN_MARKERS
        close_markers = cls.RAW_TOOL_CALL_CLOSE_MARKERS

        while index < len(text):
            markers = close_markers if inside_markup else open_markers
            next_match: tuple[int, str] | None = None
            for marker in markers:
                position = text.find(marker, index)
                if position < 0:
                    continue
                if next_match is None or position < next_match[0]:
                    next_match = (position, marker)

            if next_match is None:
                remainder = text[index:]
                if final:
                    if not inside_markup:
                        visible_parts.append(remainder)
                        remainder = ""
                    return "".join(visible_parts), remainder if inside_markup else "", inside_markup

                holdback = cls._longest_partial_tool_marker_suffix(remainder)
                visible_segment = remainder[:-holdback] if holdback else remainder
                if not inside_markup and visible_segment:
                    visible_parts.append(visible_segment)
                remainder = remainder[-holdback:] if holdback else ""
                return "".join(visible_parts), remainder, inside_markup

            position, marker = next_match
            if not inside_markup and position > index:
                visible_parts.append(text[index:position])
            index = position + len(marker)
            inside_markup = not inside_markup

        return "".join(visible_parts), "", inside_markup

    @classmethod
    def _discovery_tool_signature(
        cls,
        tool_name: str | None,
        params: dict[str, Any],
        *,
        cwd: Path,
    ) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        normalized_name = str(tool_name or "").strip()
        if normalized_name not in cls.DUPLICATE_DISCOVERY_TOOL_NAMES:
            return None

        normalized: dict[str, str] = {}
        for key, value in sorted((params or {}).items()):
            if key == "path":
                try:
                    normalized[key] = str(resolve_path(cwd, str(value or ".")))
                except Exception:
                    normalized[key] = str(value or ".")
            else:
                normalized[key] = str(value)

        if normalized_name == "glob" and "pattern" not in normalized:
            normalized["pattern"] = "**/*"
        if normalized_name == "list_dir" and "include_hidden" not in normalized:
            normalized["include_hidden"] = "False"

        return normalized_name, tuple(sorted(normalized.items()))

    async def run(
        self, message: str, user_model_content: str | list[dict] | None = None
    ):
        session = self.session
        if session is None:
            yield AgentEvent.agent_error("Session is not available.")
            return

        await session.hook_system.trigger_before_agent(user_message=message)
        yield AgentEvent.agent_start(message)
        explicit_instructions = parse_explicit_memory_instructions(message)
        if explicit_instructions:
            explicit_memory = explicit_instructions[0]
            for instruction in explicit_instructions:
                session.memory_manager.set_entry(
                    instruction.store,
                    instruction.key,
                    instruction.value,
                    source=instruction.source,
                    metadata=instruction.metadata,
                )
            session.context_manager.add_user_message(message)
            confirmation = self._explicit_memory_confirmation(
                explicit_memory, count=len(explicit_instructions)
            )
            session.context_manager.add_assistant_message(confirmation)
            await session.hook_system.trigger_after_agent(
                user_message=message,
                agent_response=confirmation,
            )
            yield AgentEvent.text_complete(confirmation, final=True)
            yield AgentEvent.agent_end(confirmation)
            return
        exact_recall = parse_exact_recall_probe(message)
        if exact_recall is not None:
            session.context_manager.add_user_message(message)
            recall = self._exact_recall_response(session, exact_recall)
            session.context_manager.add_assistant_message(recall)
            await session.hook_system.trigger_after_agent(
                user_message=message,
                agent_response=recall,
            )
            yield AgentEvent.text_complete(recall, final=True)
            yield AgentEvent.agent_end(recall)
            return
        direct_memory_answer = self._direct_memory_answer(session, message)
        if direct_memory_answer is not None:
            session.context_manager.add_user_message(message)
            session.context_manager.add_assistant_message(direct_memory_answer)
            await session.hook_system.trigger_after_agent(
                user_message=message,
                agent_response=direct_memory_answer,
            )
            yield AgentEvent.text_complete(direct_memory_answer, final=True)
            yield AgentEvent.agent_end(direct_memory_answer)
            return
        session.context_manager.add_user_message(message)
        session.change_history.begin_batch(message)
        is_execution_handoff = message.strip() == self.PLAN_EXECUTE_PROMPT
        session.todo_execution_handoff_active = is_execution_handoff
        if session.plan_mode_enabled and not is_execution_handoff:
            # Each new planning request starts a fresh question cycle.
            session.plan_questions_asked = 0
            session.plan_target_questions = self._determine_plan_question_target(
                message
            )
            session.set_plan_phase("asking_questions")
            async for seeded_event in self._seed_planning_todos_if_needed(
                session, message
            ):
                yield seeded_event
        elif not session.plan_mode_enabled and not is_execution_handoff:
            async for seeded_event in self._seed_execution_todos_if_needed(
                session, message
            ):
                yield seeded_event
        final_response: str | None = None

        try:
            async for event in self._agentic_loop(
                session,
                latest_user_text=message,
                latest_user_model_content=user_model_content,
            ):
                yield event

                if event.type == AgentEventType.TEXT_COMPLETE and bool(
                    event.data.get("final", True)
                ):
                    final_response = event.data.get("content")
        finally:
            session.todo_execution_handoff_active = False
            session.change_history.finalize_batch()

        await session.hook_system.trigger_after_agent(
            user_message=message, agent_response=final_response
        )

        yield AgentEvent.agent_end(final_response)

    def _apply_response_controls(
        self, session: Session, user_message: str, response_text: str
    ) -> str:
        text = (response_text or "").strip()
        if not text:
            return response_text

        controls = session.memory_manager.load_active_controls(user_message)
        bullet_style = str(controls.get("bullet_style", "")).strip()
        user_intent = resolve_response_intent(user_message)
        user_explicitly_wants_bullets = user_intent.explicitly_wants_bullets

        if bullet_style == "avoid" and not user_explicitly_wants_bullets:
            text = self._flatten_bullets(text)

        return text

    def _flatten_bullets(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        flattened: list[str] = []
        bullet_parts: list[str] = []

        for line in lines:
            stripped = line.strip()
            if re.match(r"^[-*]\s+", stripped):
                bullet_parts.append(re.sub(r"^[-*]\s+", "", stripped))
                continue

            if bullet_parts:
                flattened.append(
                    "; ".join(part.rstrip(".") for part in bullet_parts) + "."
                )
                bullet_parts = []

            flattened.append(line)

        if bullet_parts:
            flattened.append("; ".join(part.rstrip(".") for part in bullet_parts) + ".")

        compacted = "\n".join(part for part in flattened if part.strip())
        compacted = re.sub(r"\n{3,}", "\n\n", compacted)
        return compacted.strip()

    def _should_delay_after_compaction(self) -> bool:
        return True

    def _merge_incomplete_response_prefix(
        self,
        prefix: str,
        continuation: str,
    ) -> str:
        previous = str(prefix or "")
        current = str(continuation or "")
        if not previous:
            return current
        if not current:
            return previous

        if current.startswith(previous):
            return current
        if previous.startswith(current):
            return previous

        max_overlap = min(len(previous), len(current))
        for overlap in range(max_overlap, 0, -1):
            if previous[-overlap:] == current[:overlap]:
                return previous + current[overlap:]

        return previous + current

    def _is_heading_like_incomplete_line(self, line: str) -> bool:
        last_line = str(line or "").strip()
        if not last_line or not last_line.endswith(":"):
            return False
        heading_word_count = len(
            [part for part in re.split(r"\s+", last_line[:-1]) if part]
        )
        return heading_word_count <= 8 and bool(
            re.match(r"^(\d+[\).\s-]+)?[A-Z][A-Za-z0-9 /_-]{1,80}:$", last_line)
        )

    def _has_conclusive_ending(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if not stripped:
            return False

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return False

        last_line = lines[-1]
        if last_line.endswith(("?", "!", ".")):
            return True

        lowered = stripped.lower()
        conclusive_markers = (
            "in short",
            "in summary",
            "bottom line",
            "that should",
            "that should fix",
            "this should",
            "this is the safest path",
            "that is the fastest path",
            "you can ship",
            "you should ship",
        )
        return any(marker in lowered for marker in conclusive_markers)

    def _has_structured_continuation_context(self, text: str) -> bool:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            return False

        prior_lines = lines[:-1]
        prior_heading_count = sum(
            1 for line in prior_lines if self._is_heading_like_incomplete_line(line)
        )
        if prior_heading_count >= 1:
            return True

        numbered_or_bulleted = sum(
            1
            for line in prior_lines
            if re.match(r"^(\d+[\).\s-]+|[-*]\s+)", line)
        )
        return numbered_or_bulleted >= 2

    def _has_dangling_inline_markup(self, text: str) -> bool:
        stripped = str(text or "")
        if not stripped:
            return False

        # Ignore fenced blocks; this helper is for inline markdown/code corruption.
        without_fences = re.sub(r"```.*?```", "", stripped, flags=re.DOTALL)
        return without_fences.count("`") % 2 == 1

    def _has_incomplete_markdown_table_tail(self, text: str) -> bool:
        lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            return False

        table_lines = [line for line in lines if "|" in line]
        if len(table_lines) < 2:
            return False

        last_line = lines[-1].strip()
        if "|" not in last_line:
            return False

        nonempty_table_lines = [line.strip() for line in table_lines if line.strip()]
        if len(nonempty_table_lines) < 2:
            return False

        expected_columns = max(
            line.count("|") for line in nonempty_table_lines[:-1] if "|" in line
        )
        return last_line.count("|") < expected_columns

    def _has_empty_trailing_section(self, text: str) -> bool:
        lines = [line.rstrip() for line in str(text or "").splitlines()]
        if len(lines) < 2:
            return False

        trimmed = [line.strip() for line in lines]
        last_nonempty_index = -1
        for idx, line in enumerate(trimmed):
            if line:
                last_nonempty_index = idx
        if last_nonempty_index < 0:
            return False

        tail = trimmed[max(0, last_nonempty_index - 4) : last_nonempty_index + 1]
        if not tail:
            return False

        heading_pattern = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Za-z0-9 /_().:-]{2,90}):?$")
        if len(tail) >= 2 and heading_pattern.match(tail[-2]) and tail[-1] in {"```", "'''"}:
            return True

        if len(tail) >= 2 and heading_pattern.match(tail[-2]):
            filler = tail[-1].strip()
            if filler in {"```", "```dart", "```ts", "```tsx", "```js", "```json", "|", "-", "—", "...", "(continued)"}:
                return True
        return False

    def _should_retry_incomplete_response(
        self,
        *,
        text: str,
        finish_reason: str | None,
        retry_count: int,
        has_tool_calls: bool,
        user_message: str,
        was_streamed: bool = False,
    ) -> tuple[bool, str, int]:
        if retry_count >= self.INCOMPLETE_RESPONSE_MAX_RETRIES:
            return False, "retry cap reached", 0
        if has_tool_calls:
            return False, "tool calls present", 0

        stripped = str(text or "").strip()
        if not stripped:
            return False, "empty response", 0

        score = 0
        reasons: list[str] = []
        normalized_finish_reason = str(finish_reason or "").strip().lower()

        if stripped.count("```") % 2 == 1:
            score += 4
            reasons.append("open code fence")

        if self._has_dangling_inline_markup(stripped):
            score += 4
            reasons.append("dangling inline markup")

        lines = [line.rstrip() for line in stripped.splitlines() if line.strip()]
        last_line = lines[-1].strip() if lines else ""
        if self._is_heading_like_incomplete_line(last_line):
            score += 3
            reasons.append("dangling heading")
            if self._has_structured_continuation_context(stripped):
                score += 1
                reasons.append("structured continuation context")

        if self._has_incomplete_markdown_table_tail(stripped):
            score += 4
            reasons.append("incomplete markdown table")

        if self._has_empty_trailing_section(stripped):
            score += 4
            reasons.append("empty trailing section")

        if re.match(r"^\d+[\).\s-]+.+:$", last_line):
            score += 2
            reasons.append("numbered opener")

        if normalized_finish_reason in {"length", "max_tokens"}:
            score += 3
            reasons.append(f"finish_reason={normalized_finish_reason}")

        if resolve_response_intent(user_message).task_mode == "read_only":
            score -= 1
            reasons.append("read-only request")

        if self._has_conclusive_ending(stripped):
            score -= 3
            reasons.append("conclusive ending")

        if len(stripped) > 900 and normalized_finish_reason == "stop":
            score -= 1
            reasons.append("substantial stopped answer")

        if (
            was_streamed
            and score < 4
            and normalized_finish_reason not in {"length", "max_tokens"}
            and stripped.count("```") % 2 == 0
        ):
            reasons.append("already streamed to user")
            return False, ", ".join(reasons), score

        should_retry = score >= 2
        if not reasons:
            reasons.append("no strong truncation signal")
        return should_retry, ", ".join(reasons), score

    def _looks_incomplete_response(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if not stripped:
            return False

        if stripped.count("```") % 2 == 1:
            return True

        lines = [line.rstrip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return False

        last_line = lines[-1].strip()
        if not last_line:
            return False

        if self._is_heading_like_incomplete_line(last_line):
            return True

        if re.match(r"^P\d+\s+[–-]\s+.+:$", last_line):
            return True

        if re.match(r"^(#{1,6}\s+.+|[A-Z][A-Za-z0-9 /_-]{2,60}):$", last_line):
            return True

        return False

    def _has_pending_execution_work(self, session: Session) -> bool:
        pending = self._execution_pending_items(session)
        if not pending:
            return False

        verification_keywords = (
            "test",
            "tests",
            "lint",
            "build",
            "check",
            "verification",
            "validate",
            "validation",
            "qa",
        )
        summary_keywords = (
            "summary",
            "summarize",
            "outcome",
            "changed file",
            "changed files",
            "report",
            "final response",
            "finalize",
        )

        for item in pending:
            content = str(item.get("content", "")).strip().lower()
            if not content:
                continue
            if any(k in content for k in verification_keywords):
                continue
            if any(k in content for k in summary_keywords):
                continue
            return True
        return False

    def _should_force_execution_followthrough(
        self,
        session: Session,
        user_message: str,
    ) -> bool:
        if not self._has_pending_execution_work(session):
            return False

        intent = resolve_response_intent(user_message)
        if intent.task_mode == "read_only":
            return False
        if intent.task_mode == "execute":
            return True
        return False

    def _is_transient_post_compaction_error(self, error: str) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        transient_markers = (
            "bundled inference provider failed",
            "bundled usage is temporarily unavailable right now",
            "could not reach ite bundled inference",
            "service temporarily unavailable",
            "status 502",
            "status 503",
            "status 504",
        )
        return any(marker in text for marker in transient_markers)

    def _should_attempt_overflow_recovery(
        self,
        session: Session,
        error: str,
        *,
        overflow_compaction_attempted: bool,
    ) -> bool:
        if overflow_compaction_attempted:
            return False
        if is_context_overflow_error(error):
            return True
        if not self._is_transient_post_compaction_error(error):
            return False
        status = session.context_manager.get_compaction_status()
        current_tokens = int(status.get("current_tokens", 0) or 0)
        trigger_at = int(status.get("trigger_at", 0) or 0)
        eligible_by_messages = bool(status.get("eligible_by_messages", False))
        return bool(
            eligible_by_messages and trigger_at > 0 and current_tokens >= trigger_at
        )

    def _explicit_memory_confirmation(self, instruction, *, count: int = 1) -> str:
        if count > 1 and instruction.store == "long_term":
            return f"Got it - stored {count} conditional preferences."
        if instruction.store == "short_term":
            return f'Got it - stored "{instruction.value}" for this session.'
        if instruction.store == "semantic":
            return f'Got it - stored "{instruction.value}" for this workspace.'
        if instruction.store == "long_term":
            return f'Got it - I will remember: "{instruction.value}".'
        return "Stored."

    def _exact_recall_response(self, session: Session, probe) -> str:
        if probe.kind == "session_phrase":
            record = session.memory_manager.latest_entry("short_term")
            if record is None:
                return "No session phrase stored."
            value = str(record.get("value") or "").strip()
            value = re.sub(r"^the phrase:\s*", "", value, flags=re.IGNORECASE)
            return value or "No session phrase stored."
        return "No exact recall available."

    def _direct_memory_answer(self, session: Session, user_message: str) -> str | None:
        user_text = (user_message or "").strip()
        lowered = user_text.lower()
        if not user_text:
            return None
        if not re.match(r"^(what|which|who|where|when|how)\b", lowered):
            return None

        bundle = session.memory_manager.load_prompt_memory(user_message)
        if not isinstance(bundle, dict):
            return None

        controls = bundle.get("controls", {}) or {}
        if controls:
            return None
        if (
            bundle.get("short_term")
            or bundle.get("long_term")
            or bundle.get("episodic")
        ):
            return None

        semantic = bundle.get("semantic", {}) or {}
        if len(semantic) != 1:
            return None

        summary = str(next(iter(semantic.values()), "")).strip()
        if not summary:
            return None

        return summary if summary.endswith(".") else f"{summary}."

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
            changed_ids = (
                result.metadata.get("changed_ids", [])
                if isinstance(result.metadata, dict)
                else []
            )
            if isinstance(changed_ids, list):
                session.planning_seed_ids = [
                    str(i) for i in changed_ids if str(i).strip()
                ]

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
        if execution_items and not self._should_refresh_execution_todos(
            execution_items
        ):
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
            changed_ids = (
                result.metadata.get("changed_ids", [])
                if isinstance(result.metadata, dict)
                else []
            )
            if isinstance(changed_ids, list):
                session.execution_seed_ids = [
                    str(i) for i in changed_ids if str(i).strip()
                ]

    def _should_refresh_execution_todos(self, execution_items: list[dict]) -> bool:
        if not isinstance(execution_items, list) or not execution_items:
            return True
        if all(
            bool(item.get("completed", False))
            for item in execution_items
            if isinstance(item, dict)
        ):
            return True
        generic_markers = (
            "implement requested changes",
            "run verification checks",
            "summarize outcome and changed files",
        )
        normalized: list[str] = []
        for item in execution_items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip().lower()
            if content:
                normalized.append(content)
        if not normalized:
            return True
        return all(
            any(marker in content for marker in generic_markers)
            for content in normalized
        )

    def _should_seed_execution_todos(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if len(text) < 24:
            return False
        trivial_starts = (
            "what is",
            "show me",
            "where is",
            "explain",
            "summarize",
            "list ",
            "print ",
        )
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

    def _is_analysis_request(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        analysis_markers = (
            "audit",
            "analyze",
            "analysis",
            "inspect",
            "trace",
            "review how",
            "review the",
            "compare",
            "gap analysis",
            "challenge your own conclusions",
            "stay in analysis mode",
            "read-only",
            "without proposing code changes",
        )
        write_markers = (
            "implement",
            "fix",
            "write code",
            "patch",
            "edit",
            "update files",
            "make changes",
            "run tests",
            "verify with tests",
            "apply",
            "refactor",
        )
        has_analysis = any(marker in text for marker in analysis_markers)
        has_write = any(marker in text for marker in write_markers)
        return has_analysis and not has_write

    def _derive_analysis_seed_items(self, message: str) -> list[str]:
        first_line = ((message or "").strip().splitlines() or [""])[0].strip()
        text = re.sub(r"\s+", " ", first_line or "analysis request")
        items = [
            "Inspect relevant runtime files",
            "Build a concrete gap analysis",
            "Summarize current findings and next questions",
        ]
        if "compare" in text.lower():
            items[1] = "Compare the current implementation against the reference behavior"
        if "trace" in text.lower():
            items[0] = "Trace the runtime path through the relevant files"
        return items

    def _derive_execution_seed_items(self, message: str) -> list[str]:
        if self._is_analysis_request(message):
            return self._derive_analysis_seed_items(message)
        first_line = ((message or "").strip().splitlines() or [""])[0].strip()
        text = re.sub(r"\s+", " ", first_line or "user request")
        parts = re.split(r"\b(?:and then|then|and)\b|,|;", text, flags=re.IGNORECASE)

        verbs = (
            "build",
            "create",
            "implement",
            "fix",
            "refactor",
            "add",
            "update",
            "migrate",
            "parse",
            "export",
            "validate",
            "write",
            "generate",
        )
        tasks: list[str] = []
        for raw in parts:
            part = raw.strip(" .")
            if not part:
                continue
            lowered = part.lower()
            if not any(
                lowered.startswith(v + " ") or f" {v} " in lowered for v in verbs
            ):
                continue
            part = re.sub(
                r"^(please\s+)?(can you\s+)?", "", part, flags=re.IGNORECASE
            ).strip()
            if part:
                part = part[0].upper() + part[1:]
            if part and part not in tasks:
                tasks.append(part)
            if len(tasks) >= 4:
                break

        if not tasks:
            tasks = ["Implement requested changes"]

        tasks.append("Run verification checks (tests/lint/build as applicable)")
        tasks.append("Summarize outcome and changed files")
        return tasks[:6]

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

    def _should_suppress_malformed_tool_call(
        self,
        tool_name: str | None,
        validation_errors: list[str],
    ) -> bool:
        if tool_name not in {
            "shell",
            "read_file",
            "read_pdf",
            "read_image",
            "grep",
            "edit",
            "apply_patch",
            "memory",
        }:
            return False
        if not validation_errors:
            return False
        required_errors = {
            "shell": {"Parameter 'command': Field required"},
            "read_file": {"Parameter 'path': Field required"},
            "read_pdf": {"Parameter 'path': Field required"},
            "read_image": {"Parameter 'path': Field required"},
            "grep": {"Parameter 'pattern': Field required"},
            "edit": {
                "Parameter 'path': Field required",
                "Parameter 'new_string': Field required",
                "Parameter 'path': Field required; Parameter 'new_string': Field required",
            },
            "apply_patch": {"Parameter 'patch': Field required"},
            "memory": {"Parameter 'action': Field required"},
        }
        return set(validation_errors).issubset(required_errors.get(tool_name, set()))

    def _todo_items_for_scope(self, session: Session, scope: str) -> list[dict[str, Any]]:
        state = session.export_todos_state()
        items = state.get(scope, []) if isinstance(state, dict) else []
        return items if isinstance(items, list) else []

    def _rewrite_todo_tool_call(
        self,
        session: Session,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        normalized = dict(params)
        action = str(normalized.get("action") or "").strip().lower()
        scope = str(normalized.get("scope") or "execution").strip().lower() or "execution"
        if not action:
            return normalized, None

        existing_items = self._todo_items_for_scope(session, scope)
        has_existing_items = bool(existing_items)
        item_values = normalized.get("items")
        has_items = isinstance(item_values, list) and any(
            str(item).strip() for item in item_values
        )
        content_value = normalized.get("content")
        has_content = isinstance(content_value, str) and bool(content_value.strip())
        has_id = bool(str(normalized.get("id") or "").strip())

        if action == "add" and has_existing_items:
            return (
                {
                    "action": "list",
                    "scope": scope,
                    "_suppress_ui": True,
                    "_runtime_reused_checklist": True,
                },
                "Runtime-owned checklist already exists; listing current items instead of creating a second checklist.",
            )

        if action in {"complete", "update", "remove", "reopen"} and has_existing_items and not has_id:
            return (
                {
                    "action": "list",
                    "scope": scope,
                    "_suppress_ui": True,
                    "_runtime_reused_checklist": True,
                },
                "Checklist item reference was missing; listing current items so the agent can reuse existing todo IDs.",
            )

        if action == "add" and not has_existing_items and not (has_items or has_content):
            return (
                normalized,
                "Checklist creation omitted todo content.",
            )

        return normalized, None

    def _is_planning_todo_already_completed(
        self, session: Session, todo_id: str
    ) -> bool:
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
        async for e in self._complete_execution_todo_id(session, todo_id):
            yield e

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

    def _is_execution_todo_already_completed(
        self, session: Session, todo_id: str
    ) -> bool:
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

    def _execution_pending_items(self, session: Session) -> list[dict]:
        state = session.export_todos_state()
        execution = state.get("execution", []) if isinstance(state, dict) else []
        if not isinstance(execution, list):
            return []
        pending: list[dict] = []
        for item in execution:
            if not isinstance(item, dict):
                continue
            if bool(item.get("completed", False)):
                continue
            pending.append(item)
        return pending

    def _next_pending_execution_todo_id(self, session: Session) -> str | None:
        for item in self._execution_pending_items(session):
            value = str(item.get("id", "")).strip()
            if value:
                return value
        return None

    def _find_pending_execution_todo_id_by_keywords(
        self,
        session: Session,
        keywords: tuple[str, ...],
    ) -> str | None:
        for item in self._execution_pending_items(session):
            content = str(item.get("content", "")).strip().lower()
            if not content:
                continue
            if any(k in content for k in keywords):
                value = str(item.get("id", "")).strip()
                if value:
                    return value
        return None

    async def _complete_execution_todo_id(
        self,
        session: Session,
        todo_id: str | None,
    ) -> AsyncGenerator[AgentEvent, None]:
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

    async def _complete_execution_stage_todo(
        self,
        session: Session,
        *,
        stage: str,
    ) -> AsyncGenerator[AgentEvent, None]:
        verification_keywords = (
            "test",
            "tests",
            "lint",
            "build",
            "check",
            "verification",
            "validate",
            "validation",
            "qa",
        )
        summary_keywords = (
            "summary",
            "summarize",
            "outcome",
            "changed file",
            "changed files",
            "report",
            "final response",
            "finalize",
        )

        if stage == "verification":
            todo_id = self._find_pending_execution_todo_id_by_keywords(
                session,
                verification_keywords,
            ) or self._next_pending_execution_todo_id(session)
            async for e in self._complete_execution_todo_id(session, todo_id):
                yield e
            return

        if stage == "summary":
            todo_id = self._find_pending_execution_todo_id_by_keywords(
                session,
                summary_keywords,
            ) or self._next_pending_execution_todo_id(session)
            async for e in self._complete_execution_todo_id(session, todo_id):
                yield e
            return

        # Default implementation stage: prefer non-verification/non-summary tasks.
        todo_id: str | None = None
        for item in self._execution_pending_items(session):
            content = str(item.get("content", "")).strip().lower()
            if not content:
                continue
            if any(k in content for k in verification_keywords):
                continue
            if any(k in content for k in summary_keywords):
                continue
            value = str(item.get("id", "")).strip()
            if value:
                todo_id = value
                break
        if not todo_id:
            todo_id = self._next_pending_execution_todo_id(session)
        async for e in self._complete_execution_todo_id(session, todo_id):
            yield e

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

    def _is_implementation_progress_tool(
        self,
        *,
        tool_name: str,
        arguments: dict,
    ) -> bool:
        if tool_name in {"write_file", "edit", "apply_patch"}:
            return True
        if tool_name == "shell":
            command = str(arguments.get("command", "")).strip()
            return not self._is_verification_command(command)
        return False

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
            async for progress_event in self._complete_execution_stage_todo(
                session,
                stage="implementation",
            ):
                yield progress_event
            return

        if tool_name == "shell":
            command = str(arguments.get("command", "")).strip()
            if self._is_verification_command(command):
                async for progress_event in self._complete_execution_stage_todo(
                    session,
                    stage="verification",
                ):
                    yield progress_event
                return
            # Non-verification shell work still counts as implementation progress.
            async for progress_event in self._complete_execution_stage_todo(
                session,
                stage="implementation",
            ):
                yield progress_event

    async def _agentic_loop(
        self,
        session: Session,
        *,
        latest_user_text: str,
        latest_user_model_content: str | list[dict] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        max_turns = self.config.max_turns
        overflow_compaction_attempted = False
        execution_progress_made = False
        implementation_progress_made = False
        empty_reply_retries = 0
        post_compaction_recovery_active = False
        post_compaction_continue_prompt_needed = False
        post_compaction_retry_attempts = 0
        incomplete_response_retries = 0
        incomplete_response_prefix = ""
        discovery_result_cache: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            ToolResult,
        ] = {}
        repeated_discovery_stalls = 0
        turn_num = 0
        current_visual_budget: int | None = None

        while turn_num < max_turns:
            if self.session is not session:
                yield AgentEvent.agent_error("Session changed while turn was running.")
                return

            response_text = ""
            streamed_visible_text = False
            raw_tool_markup_buffer = ""
            inside_raw_tool_markup = False
            execution_progress_eligible = False

            session.context_manager.microcompact_tool_outputs()
            if session.context_manager.needs_compression():
                trigger_tokens = (
                    session.context_manager.estimate_current_context_tokens()
                )
                context_window = self.config.model.context_window
                preserved_messages = session.context_manager.select_compaction_tail()
                yield AgentEvent.context_compacting(trigger_reason="threshold")
                summary, usage = await session.chat_compactor.compact(
                    session.context_manager
                )

                if summary:
                    lifecycle_focus = session._derive_current_focus()
                    artifact_id = session.compact_artifact_manager.save_summary(summary)
                    session.context_manager.replace_with_summary(
                        summary,
                        boundary_metadata={
                            "trigger_reason": "threshold",
                            "trigger_tokens": trigger_tokens,
                            "context_window": context_window,
                            "summary_chars": len(summary),
                            "summary_artifact_id": artifact_id,
                            "compaction_count": session.context_manager.compaction_count
                            + 1,
                        },
                        preserved_messages=preserved_messages,
                    )
                    session.record_lifecycle_episode(
                        session.build_lifecycle_summary(
                            f"Context compacted after {session.turn_count} turns",
                            focus_hint=lifecycle_focus,
                        ),
                        source="context_compaction",
                    )
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
                        trigger_reason="threshold",
                        auto_resume_required=True,
                    )
                    return

            session.increment_turn()
            turn_num += 1

            tool_schemas = session.tool_registry.get_schemas()

            tool_calls: list[ToolCall] = []
            usage: TokenUsage | None = None
            stream_error: str | None = None
            finish_reason: str | None = None

            outbound_messages = session.context_manager.get_prompt_messages(
                latest_user_text
            )
            if post_compaction_continue_prompt_needed:
                outbound_messages.append(
                    {
                        "role": "user",
                        "content": self.POST_COMPACTION_CONTINUE_PROMPT,
                    }
                )
                post_compaction_continue_prompt_needed = False
            if latest_user_model_content is not None:
                for msg in reversed(outbound_messages):
                    if (
                        msg.get("role") == "user"
                        and msg.get("content") == latest_user_text
                    ):
                        msg["content"] = latest_user_model_content
                        break

            chat_completion_kwargs = {
                "tools": tool_schemas if tool_schemas else None,
                "stream": True,
            }
            if current_visual_budget is not None:
                chat_completion_kwargs["visual_budget"] = current_visual_budget

            async for event in session.client.chat_completion(
                outbound_messages,
                **chat_completion_kwargs,
            ):
                if event.type == StreamEventType.TEXT_DELTA:
                    if event.text_delta:
                        content = event.text_delta.content
                        visible_content, raw_tool_markup_buffer, inside_raw_tool_markup = (
                            self._consume_raw_tool_call_markup(
                                raw_tool_markup_buffer + content,
                                inside_markup=inside_raw_tool_markup,
                            )
                        )
                        response_text += visible_content
                        # In plan mode (pre-execution), suppress live text streaming.
                        # This prevents partial/final plan text from rendering before
                        # question flow is complete.
                        if visible_content and not (
                            session.plan_mode_enabled
                            and session.plan_phase != "executing"
                        ):
                            streamed_visible_text = True
                            yield AgentEvent.text_delta(visible_content)
                elif event.type == StreamEventType.TOOL_CALL_COMPLETE:
                    if event.tool_call:
                        tool_calls.append(event.tool_call)
                elif event.type == StreamEventType.ERROR:
                    stream_error = event.error or "Unknown error occurred"
                    break
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage
                    finish_reason = event.finish_reason

            visible_tail, raw_tool_markup_buffer, inside_raw_tool_markup = (
                self._consume_raw_tool_call_markup(
                    raw_tool_markup_buffer,
                    inside_markup=inside_raw_tool_markup,
                    final=True,
                )
            )
            if visible_tail:
                response_text += visible_tail

            if stream_error:
                if self._should_attempt_overflow_recovery(
                    session,
                    stream_error,
                    overflow_compaction_attempted=overflow_compaction_attempted,
                ):
                    overflow_compaction_attempted = True
                    trigger_tokens = (
                        session.context_manager.estimate_current_context_tokens()
                    )
                    context_window = self.config.model.context_window
                    preserved_messages = (
                        session.context_manager.select_compaction_tail()
                    )
                    yield AgentEvent.context_compacting(trigger_reason="overflow_retry")
                    summary, compact_usage = await session.chat_compactor.compact(
                        session.context_manager
                    )
                    if summary:
                        lifecycle_focus = session._derive_current_focus()
                        artifact_id = session.compact_artifact_manager.save_summary(
                            summary
                        )
                        session.context_manager.replace_with_summary(
                            summary,
                            boundary_metadata={
                                "trigger_reason": "overflow_retry",
                                "trigger_tokens": trigger_tokens,
                                "context_window": context_window,
                                "summary_chars": len(summary),
                                "summary_artifact_id": artifact_id,
                                "compaction_count": session.context_manager.compaction_count
                                + 1,
                            },
                            preserved_messages=preserved_messages,
                        )
                        session.record_lifecycle_episode(
                            session.build_lifecycle_summary(
                                f"Context compacted after overflow at turn {session.turn_count}",
                                focus_hint=lifecycle_focus,
                            ),
                            source="context_compaction_overflow_retry",
                        )
                        compacted_tokens = (
                            session.context_manager.estimate_current_context_tokens()
                        )
                        session.context_manager.set_latest_usage(
                            TokenUsage(
                                prompt_tokens=compacted_tokens,
                                completion_tokens=0,
                                total_tokens=compacted_tokens,
                                cached_tokens=0,
                            )
                        )
                        if compact_usage:
                            session.context_manager.add_usage(compact_usage)
                        yield AgentEvent.context_compacted(
                            trigger_tokens=trigger_tokens,
                            context_window=context_window,
                            summary_chars=len(summary),
                            trigger_reason="overflow_retry",
                            auto_resume_required=True,
                        )
                        return
                if (
                    post_compaction_recovery_active
                    and post_compaction_retry_attempts
                    < self.POST_COMPACTION_MAX_RECOVERY_RETRIES
                    and self._is_transient_post_compaction_error(stream_error)
                ):
                    post_compaction_retry_attempts += 1
                    await asyncio.sleep(float(post_compaction_retry_attempts))
                    continue
                post_compaction_recovery_active = False
                post_compaction_continue_prompt_needed = False
                yield AgentEvent.agent_error(stream_error)
                # Fail this turn immediately instead of looping and repeating
                # the same upstream/provider error up to max_turns.
                return

            if session.plan_mode_enabled and session.plan_phase != "executing":
                # Deterministic planner UX: process at most one structured question per turn.
                plan_calls = [tc for tc in tool_calls if tc.name == "plan_question"]
                if len(plan_calls) > 1:
                    first_call = plan_calls[0]
                    non_plan_calls = [
                        tc for tc in tool_calls if tc.name != "plan_question"
                    ]
                    tool_calls = non_plan_calls + [first_call]
                target_questions = max(
                    self.PLAN_MIN_QUESTIONS,
                    min(
                        self.PLAN_MAX_QUESTIONS,
                        int(
                            getattr(
                                session,
                                "plan_target_questions",
                                self.PLAN_MIN_QUESTIONS,
                            )
                        ),
                    ),
                )
                session.plan_target_questions = target_questions
                # Once enough questions are asked, transition to deterministic writing phase:
                # no extra tool calls should run before final plan output.
                if session.plan_questions_asked >= target_questions and tool_calls:
                    session.set_plan_phase("writing_plan")
                    session.context_manager.add_user_message(
                        "Question phase is complete. Do not call more tools now. "
                        "Write the final implementation plan directly with all required sections."
                    )
                    continue

            controlled_response_text = self._apply_response_controls(
                session,
                latest_user_text,
                response_text,
            )
            if incomplete_response_prefix and controlled_response_text and not tool_calls:
                controlled_response_text = self._merge_incomplete_response_prefix(
                    incomplete_response_prefix,
                    controlled_response_text,
                )
                incomplete_response_prefix = ""
            has_visible_response = bool(controlled_response_text.strip())
            if has_visible_response or tool_calls:
                empty_reply_retries = 0

            if (
                not tool_calls
                and has_visible_response
                and not session.plan_mode_enabled
                and self._should_force_execution_followthrough(
                    session,
                    latest_user_text,
                )
                and not implementation_progress_made
            ):
                session.context_manager.add_system_message(
                    "Execution checklist still has unfinished implementation work. "
                    "Do not stop with a status update only. Perform the next required tool call or file edit now."
                )
                continue

            session.context_manager.add_assistant_message(
                controlled_response_text,
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
                session.context_manager.microcompact_tool_outputs()
                session.context_manager.prune_tool_outputs()
                if not has_visible_response and not session.plan_mode_enabled:
                    if empty_reply_retries < 2:
                        empty_reply_retries += 1
                        session.context_manager.add_system_message(
                            "The previous assistant reply was empty. Continue the task now. "
                            "Either call the next required tool or provide a concise completion summary."
                        )
                        continue
                    yield AgentEvent.agent_error(
                        "The model stopped without responding after tool execution."
                    )
                    return
                if session.plan_mode_enabled:
                    if session.plan_phase != "executing":
                        target_questions = max(
                            self.PLAN_MIN_QUESTIONS,
                            min(
                                self.PLAN_MAX_QUESTIONS,
                                int(
                                    getattr(
                                        session,
                                        "plan_target_questions",
                                        self.PLAN_MIN_QUESTIONS,
                                    )
                                ),
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
                        if not controlled_response_text.strip():
                            session.set_plan_phase("writing_plan")
                            session.context_manager.add_user_message(
                                "Now write the complete final implementation plan with the required "
                                "sections. Do not ask more questions in this turn."
                            )
                            continue
                        session.set_plan_phase("awaiting_implementation_confirmation")
                        plan_text = self._select_plan_text(
                            session, controlled_response_text
                        )
                        if plan_text.strip():
                            session.set_pending_plan(plan_text)
                            async for (
                                progress_event
                            ) in self._complete_planning_seed_todo(session, 1):
                                yield progress_event
                            async for (
                                progress_event
                            ) in self._complete_planning_seed_todo(session, 2):
                                yield progress_event
                            yield AgentEvent.text_complete(plan_text, final=True)
                            session.loop_detector.record_action(
                                "response", text=plan_text
                            )
                            yield AgentEvent.plan_ready(plan_text)
                    else:
                        if controlled_response_text:
                            if execution_progress_made:
                                async for (
                                    progress_event
                                ) in self._complete_execution_stage_todo(
                                    session,
                                    stage="summary",
                                ):
                                    yield progress_event
                            yield AgentEvent.text_complete(
                                controlled_response_text,
                                final=True,
                            )
                            session.loop_detector.record_action(
                                "response", text=controlled_response_text
                            )
                        session.set_plan_phase("idle")
                elif controlled_response_text:
                    should_retry_incomplete, retry_reason, retry_score = (
                        self._should_retry_incomplete_response(
                            text=controlled_response_text,
                            finish_reason=finish_reason,
                            retry_count=incomplete_response_retries,
                            has_tool_calls=bool(tool_calls),
                            user_message=latest_user_text,
                            was_streamed=streamed_visible_text,
                        )
                    )
                    if should_retry_incomplete:
                        incomplete_response_retries += 1
                        incomplete_response_prefix = controlled_response_text
                        session.context_manager.add_system_message(
                            "The previous assistant response appears incomplete. "
                            "Continue exactly where you left off, finish the structure, "
                            "and do not repeat already written content. "
                            f"Retry reason: {retry_reason}. "
                            f"Confidence score: {retry_score}."
                        )
                        continue
                    if execution_progress_made:
                        async for progress_event in self._complete_execution_stage_todo(
                            session,
                            stage="summary",
                        ):
                            yield progress_event
                    yield AgentEvent.text_complete(
                        controlled_response_text,
                        final=True,
                    )
                    session.loop_detector.record_action(
                        "response", text=controlled_response_text
                    )
                post_compaction_recovery_active = False
                post_compaction_continue_prompt_needed = False
                incomplete_response_prefix = ""
                return

            if controlled_response_text and tool_calls:
                in_plan_questioning = (
                    session.plan_mode_enabled and session.plan_phase != "executing"
                )
                if not in_plan_questioning:
                    yield AgentEvent.text_complete(
                        controlled_response_text,
                        final=False,
                        continue_after=True,
                    )
                session.loop_detector.record_action(
                    "response", text=controlled_response_text
                )

            tool_call_results: list[tuple[str, ToolResultMessage, ToolResult]] = []
            skipped_plan_validation_errors: list[str] = []
            seen_discovery_calls: set[
                tuple[str, tuple[tuple[str, str], ...]]
            ] = set()
            actual_tool_execution_count = 0
            repeated_discovery_reuse_count = 0
            for tool_call in tool_calls:
                tool = session.tool_registry.get(tool_call.name)
                effective_args = dict(tool_call.arguments)
                normalized_args = effective_args
                validation_errors: list[str] = []
                if tool is not None:
                    normalized_args = session.tool_registry.normalize_params(
                        tool_name=tool_call.name,
                        params=effective_args,
                        plan_mode_enabled=session.plan_mode_enabled,
                        plan_phase=session.plan_phase,
                    )
                    if tool_call.name == "todos":
                        normalized_args, _todo_note = self._rewrite_todo_tool_call(
                            session, normalized_args
                        )
                    effective_args = normalized_args
                    validation_errors = tool.validate_params(normalized_args)

                if (
                    session.plan_mode_enabled
                    and session.plan_phase != "executing"
                    and tool_call.name != "plan_question"
                ):
                    if validation_errors:
                        skipped_plan_validation_errors.append(
                            f"{tool_call.name}: {'; '.join(validation_errors)}"
                        )
                        continue

                if validation_errors and self._should_suppress_malformed_tool_call(
                    tool_call.name, validation_errors
                ):
                    suppressed_result = ToolResult.error_result(
                        f"Invalid parameters: {'; '.join(validation_errors)}",
                        metadata={
                            "recoverable": True,
                            "suppressed": True,
                            "validation_errors": validation_errors,
                            "recovery_hint": "Retry with all required arguments.",
                        },
                    )
                    tool_call_results.append(
                        (
                            tool_call.name or "tool",
                            ToolResultMessage(
                                tool_call_id=tool_call.call_id,
                                content=(
                                    "Error: Invalid parameters: "
                                    + "; ".join(validation_errors)
                                    + "\n\nOutput:\nRetry this tool with all required arguments."
                                ),
                                is_error=True,
                            ),
                            suppressed_result,
                        )
                    )
                    yield AgentEvent.tool_call_complete(
                        tool_call.call_id,
                        tool_call.name or "tool",
                        suppressed_result,
                    )
                    continue

                discovery_signature = self._discovery_tool_signature(
                    tool_call.name,
                    effective_args,
                    cwd=self.config.cwd,
                )
                if discovery_signature is not None:
                    cached_discovery_result = discovery_result_cache.get(
                        discovery_signature
                    )
                    if cached_discovery_result is not None:
                        repeated_discovery_reuse_count += 1
                        reused_result = ToolResult.success_result(
                            cached_discovery_result.output,
                            metadata={
                                **(
                                    cached_discovery_result.metadata
                                    if isinstance(
                                        cached_discovery_result.metadata, dict
                                    )
                                    else {}
                                ),
                                "reused_cached_discovery": True,
                                "recovery_hint": (
                                    "This same discovery command already succeeded earlier in this request. "
                                    "Use the cached result and take the next step."
                                ),
                            },
                            truncated=cached_discovery_result.truncated,
                            exit_code=cached_discovery_result.exit_code,
                        )
                        tool_call_results.append(
                            (
                                tool_call.name or "tool",
                                ToolResultMessage(
                                    tool_call_id=tool_call.call_id,
                                    content=reused_result.to_model_output(),
                                    is_error=False,
                                ),
                                reused_result,
                            )
                        )
                        yield AgentEvent.tool_call_complete(
                            tool_call.call_id,
                            tool_call.name or "tool",
                            reused_result,
                        )
                        continue
                    if discovery_signature in seen_discovery_calls:
                        repeated_discovery_reuse_count += 1
                        duplicate_result = ToolResult.error_result(
                            "Duplicate discovery call suppressed.",
                            metadata={
                                "recoverable": True,
                                "suppressed": True,
                                "duplicate_discovery_call": True,
                                "recovery_hint": (
                                    "You already ran this same discovery command in this turn. "
                                    "Use the previous result and take the next step instead of repeating it."
                                ),
                            },
                        )
                        tool_call_results.append(
                            (
                                tool_call.name or "tool",
                                ToolResultMessage(
                                    tool_call_id=tool_call.call_id,
                                    content=(
                                        "Error: Duplicate discovery call suppressed."
                                        "\n\nOutput:\nYou already ran this same discovery command in this turn. "
                                        "Use the previous result and take the next step instead of repeating it."
                                    ),
                                    is_error=True,
                                ),
                                duplicate_result,
                            )
                        )
                        yield AgentEvent.tool_call_complete(
                            tool_call.call_id,
                            tool_call.name or "tool",
                            duplicate_result,
                        )
                        continue
                    seen_discovery_calls.add(discovery_signature)

                yield AgentEvent.tool_call_start(
                    tool_call.call_id,
                    tool_call.name,
                    effective_args,
                )
                actual_tool_execution_count += 1

                session.loop_detector.record_action(
                    "tool_call",
                    tool_name=tool_call.name,
                    args=effective_args,
                    cwd=self.config.cwd,
                )

                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise asyncio.CancelledError

                progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

                async def on_tool_progress(update: dict[str, Any]) -> None:
                    await progress_queue.put(update)

                invoke_task = asyncio.create_task(
                    session.tool_registry.invoke(
                        tool_call.name,
                        effective_args,
                        self.config.cwd,
                        session.hook_system,
                        session.approval_manager,
                        tool_call_id=tool_call.call_id,
                        session_id=session.session_id,
                        plan_mode_enabled=session.plan_mode_enabled,
                        plan_phase=session.plan_phase,
                        todo_execution_handoff_active=session.todo_execution_handoff_active,
                        set_plan_phase=session.set_plan_phase,
                        plan_question_callback=self.plan_question_callback,
                        progress_callback=on_tool_progress,
                    )
                )

                while True:
                    try:
                        update = await asyncio.wait_for(
                            progress_queue.get(), timeout=0.05
                        )
                    except asyncio.TimeoutError:
                        if invoke_task.done():
                            break
                        continue
                    yield AgentEvent.tool_call_progress(
                        tool_call.call_id,
                        tool_call.name,
                        output=str(update.get("output") or ""),
                        metadata=update.get("metadata")
                        if isinstance(update.get("metadata"), dict)
                        else {},
                        success=bool(update.get("success", True)),
                        error=str(update.get("error") or "") or None,
                        exit_code=update.get("exit_code"),
                    )

                while not progress_queue.empty():
                    update = progress_queue.get_nowait()
                    yield AgentEvent.tool_call_progress(
                        tool_call.call_id,
                        tool_call.name,
                        output=str(update.get("output") or ""),
                        metadata=update.get("metadata")
                        if isinstance(update.get("metadata"), dict)
                        else {},
                        success=bool(update.get("success", True)),
                        error=str(update.get("error") or "") or None,
                        exit_code=update.get("exit_code"),
                    )

                result = await invoke_task
                if tool_call.name == "todos" and effective_args.get("_suppress_ui"):
                    result.metadata = result.metadata or {}
                    result.metadata["suppressed"] = True
                    result.metadata["runtime_reused_checklist"] = True

                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise asyncio.CancelledError

                if result.success and tool_call.name not in {"todos", "plan_question"}:
                    execution_progress_eligible = True
                    execution_progress_made = True
                    if self._is_implementation_progress_tool(
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                    ):
                        implementation_progress_made = True
                    if tool_call.name in {"write_file", "edit", "apply_patch"}:
                        diffs = file_diffs_from_tool_result(result)
                        if diffs:
                            session.change_history.record_file_diffs(diffs)

                if tool_call.name == "read_image" and result.success:
                    image_path = result.metadata.get("cached_path") or result.metadata.get("path")
                    budget = effective_args.get("budget", 280)
                    if image_path:
                        current_visual_budget = budget
                        # Inject visual content into the most recent user message
                        # to follow the "Modality Order" (Images before Text).
                        messages = session.context_manager.get_messages()
                        for msg in reversed(messages):
                            if msg.get("role") == "user":
                                content = msg.get("content")
                                if isinstance(content, str):
                                    # Convert existing text to a multimodal list
                                    msg["content"] = [
                                        {"type": "image_url", "image_url": {"url": f"file://{image_path}"}},
                                        {"type": "text", "text": content},
                                    ]
                                elif isinstance(content, list):
                                    # Prepend the image to the list
                                    content.insert(0, {"type": "image_url", "image_url": {"url": f"file://{image_path}"}})
                                break

                if tool_call.name == "plan_question" and result.success:
                    session.increment_plan_questions()
                    session.set_plan_phase("writing_plan")
                    target_questions = max(
                        self.PLAN_MIN_QUESTIONS,
                        min(
                            self.PLAN_MAX_QUESTIONS,
                            int(
                                getattr(
                                    session,
                                    "plan_target_questions",
                                    self.PLAN_MIN_QUESTIONS,
                                )
                            ),
                        ),
                    )
                    if session.plan_questions_asked >= target_questions:
                        async for progress_event in self._complete_planning_seed_todo(
                            session, 0
                        ):
                            yield progress_event
                elif self._has_execution_todos(session):
                    async for (
                        progress_event
                    ) in self._auto_progress_execution_todos_on_tool(
                        session,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        success=result.success,
                    ):
                        yield progress_event

                if discovery_signature is not None and result.success:
                    discovery_result_cache[discovery_signature] = result

                yield AgentEvent.tool_call_complete(
                    tool_call.call_id,
                    tool_call.name,
                    result,
                )

                tool_call_results.append(
                    (
                        tool_call.name or "tool",
                        ToolResultMessage(
                            tool_call_id=tool_call.call_id,
                            content=result.to_model_output(),
                            is_error=not result.success,
                        ),
                        result,
                    )
                )
            for tool_name, tool_result, result in tool_call_results:
                session.context_manager.add_tool_result(
                    tool_result.tool_call_id,
                    tool_result.content,
                    tool_ui={
                        "name": tool_name,
                        "success": result.success,
                        "output": result.output,
                        "error": result.error,
                        "metadata": result.metadata,
                        "diff": result.diff.to_diff() if result.diff else None,
                        "truncated": result.truncated,
                        "exit_code": result.exit_code,
                    },
                )

            if skipped_plan_validation_errors:
                session.context_manager.add_user_message(
                    "The previous planning tool call had missing required parameters and was ignored: "
                    + " | ".join(skipped_plan_validation_errors)
                    + ". Retry with complete required arguments before continuing."
                )

            if (
                tool_calls
                and actual_tool_execution_count == 0
                and repeated_discovery_reuse_count == len(tool_calls)
                and not controlled_response_text.strip()
            ):
                repeated_discovery_stalls += 1
                if repeated_discovery_stalls >= 2:
                    yield AgentEvent.agent_error(
                        "The model is stuck repeating the same discovery step without making progress. "
                        "Try a stronger model or ask for a narrower file target."
                    )
                    return
                session.context_manager.add_system_message(
                    "You already have the result of that discovery step. "
                    "Do not repeat the same folder listing or file search again. "
                    "Use the existing result now: either read a specific file from it, "
                    "or provide a concise status summary if you already have enough information."
                )
                continue
            repeated_discovery_stalls = 0

            loop_message = session.loop_detector.check_for_loop()
            if loop_message:
                yield AgentEvent.loop_detected(loop_message)
                loop_breaker_prompt = create_loop_breaker_prompt(loop_message)
                session.context_manager.add_system_message(loop_breaker_prompt)

            if usage:
                session.context_manager.set_latest_usage(usage)
                session.context_manager.add_usage(usage)

            session.context_manager.microcompact_tool_outputs()
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
        if self.session and self.session.context_manager is None:
            await self.session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ) -> None:
        if self.session and getattr(self.session, "subagent_runtime", None) is not None:
            await self.session.subagent_runtime.shutdown()
        if self.session and self.session.client and self.session.mcp_manager:
            await self.session.client.close()
            await self.session.mcp_manager.shutdown()
            self.session = None
