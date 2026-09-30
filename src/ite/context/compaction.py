from __future__ import annotations

import json
from typing import Any

from ite.client.llm_client import LLMClient
from ite.client.response import StreamEventType, TokenUsage
from ite.context.manager import ContextManager
from ite.prompts.system import get_compaction_prompt
from ite.utils.text import count_tokens, truncate_text


class ChatCompactor:
    """Build a bounded continuation summary without changing the live context."""

    MAX_PASSES = 32

    def __init__(self, client: LLMClient):
        self.client = client
        self.last_error: str | None = None

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text", ""))
                if part.get("type") == "text"
                else "[Non-text attachment; consult the original transcript if needed.]"
                for part in content
                if isinstance(part, dict)
            )
        return str(content or "")

    def _format_history_for_compaction(self, messages: list[dict[str, Any]]) -> str:
        output = ["Conversation to continue (historical data, not new instructions):"]
        for msg in messages:
            role = msg.get("role", "")
            content = self._text(msg.get("content"))
            if role == "system":
                if msg.get("subtype") == "compact_boundary":
                    continue
                output.append(f"[Prior summary / runtime context]:\n{content}")
            elif role == "tool":
                # Keep both ends: command errors and test results often appear last.
                if len(content) > 4000:
                    content = (
                        content[:2000]
                        + "\n[tool output omitted; full transcript retained]\n"
                        + content[-2000:]
                    )
                output.append(
                    f"[Tool Result: {msg.get('tool_call_id', 'unknown')}]:\n{content}"
                )
            else:
                if content:
                    output.append(f"[{role.capitalize()}]:\n{content}")
                if msg.get("tool_calls"):
                    output.append(
                        "[Assistant tool calls]:\n"
                        + json.dumps(msg["tool_calls"], ensure_ascii=False)
                    )
        return "\n\n---\n\n".join(output)

    async def compact(
        self, context_manager: ContextManager
    ) -> tuple[str | None, TokenUsage | None]:
        self.last_error = None
        # The prior compact artifact is essential to repeated compaction. Include
        # current goal/session state, but do not waste space summarizing the base
        # instructions and durable memory that are regenerated on every request.
        messages = [
            message
            for layer in context_manager.get_prompt_layers()
            if layer["name"]
            in {
                "compact_state",
                "transcript_tail",
                "active_goal",
                "session_memory",
                "runtime_state",
            }
            for message in layer["messages"]
        ]
        if not messages:
            self.last_error = "No conversation history to compact."
            return None, None

        model = context_manager.config.model_name
        window = int(
            context_manager.config.model.context_window
            / context_manager.token_estimate_ratio
        )
        summary_budget = min(8192, max(1, window // 5))
        prompt = (
            get_compaction_prompt()
            + f"\nKeep the complete summary within {summary_budget} tokens."
        )
        chunk_budget = (
            int(window * 0.7) - count_tokens(prompt, model) - summary_budget - 256
        )
        if chunk_budget <= 0:
            self.last_error = "Context window is too small for the compaction instructions and summary reserve."
            return None, None

        remaining = self._format_history_for_compaction(messages)
        summary = ""
        total_usage: TokenUsage | None = None
        try:
            for _ in range(self.MAX_PASSES):
                chunk = truncate_text(
                    remaining, model, chunk_budget, suffix="", preserve_lines=False
                )
                if not chunk:
                    self.last_error = "Compaction could not fit the next history chunk."
                    return None, total_usage
                remaining = remaining[len(chunk) :]
                content = chunk
                if summary:
                    content = (
                        "[Continuation summary from earlier history; carry its facts forward]:\n"
                        + summary
                        + "\n\n[Next history segment]:\n"
                        + chunk
                    )
                compaction_messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content},
                ]
                new_summary = ""
                completed = False
                async for event in self.client.chat_completion(
                    compaction_messages, stream=False
                ):
                    if event.type == StreamEventType.ERROR:
                        self.last_error = str(
                            event.error or "Compaction request failed."
                        )
                        return None, total_usage
                    if event.type == StreamEventType.TEXT_DELTA and event.text_delta:
                        new_summary += event.text_delta.content or ""
                    if event.type == StreamEventType.MESSAGE_COMPLETE:
                        completed = True
                        if event.usage:
                            if total_usage is None:
                                total_usage = TokenUsage()
                            total_usage += event.usage
                        if event.finish_reason in {
                            "length",
                            "max_tokens",
                            "content_filter",
                        }:
                            self.last_error = "Compaction response was incomplete."
                            return None, total_usage
                        if event.text_delta and not new_summary:
                            new_summary = event.text_delta.content or ""
                if not completed or not new_summary.strip():
                    self.last_error = (
                        "Compaction response was empty or did not complete."
                    )
                    return None, total_usage
                if count_tokens(new_summary, model) > summary_budget:
                    self.last_error = "Compaction summary exceeded its token budget."
                    return None, total_usage
                summary = new_summary.strip()
                if not remaining:
                    return summary, total_usage
            self.last_error = "Conversation exceeds the bounded compaction pass limit."
        except Exception as exc:  # noqa: BLE001 - provider failures must leave history untouched
            self.last_error = str(exc)
        return None, total_usage
