from typing import Any
from ite.prompts.system import get_compaction_prompt
from ite.client.response import StreamEventType
from ite.client.response import TokenUsage
from ite.context.manager import ContextManager
from ite.client.llm_client import LLMClient


class ChatCompactor:
    def __init__(self, client: LLMClient):
        self.client = client
        self.last_error: str | None = None

    def _format_history_for_compaction(self, messages: list[dict[str, Any]]) -> str:
        output = ["Here is the conversation that needs to be continued: \n"]
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")

            if role == "system":
                continue

            if role == "tool":
                tool_id = msg.get("tool_call_id", "unknown")

                truncated = content[:2000] if len(content) > 2000 else content

                if len(content) > 2000:
                    truncated += "\n... [tool output truncated]"

                output.append(f"[Tool Result: {tool_id}]:\n{truncated}")

            elif role == "assistant":
                tool_details = []
                if content:
                    truncated = content[:3000] if len(content) > 3000 else content

                    if len(content) > 3000:
                        truncated += "\n... [response truncated]"

                    output.append(f"[Assistant]:\n{truncated}")

                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        args = func.get("arguments", "{}")

                        if len(args) > 500:
                            args = args[:500]

                        tool_details.append(f"  - {name}({args})")

                    output.append("Assistant called tools\n" + "\n".join(tool_details))
            else:
                trunctated = content[:1500] if len(content) > 1500 else content

                if len(content) > 1500:
                    trunctated += "\n... [message truncated]"

                output.append(f"User:\n{trunctated}")

        return "\n\n---\n\n".join(output)

    async def compact(
        self, context_manager: ContextManager
    ) -> tuple[
        str | None,
        TokenUsage | None,
    ]:
        self.last_error = None
        messages = context_manager.get_messages()

        if len(messages) < 3:
            return None, None

        compaction_messages = [
            {
                "role": "system",
                "content": get_compaction_prompt(),
            },
            {
                "role": "user",
                "content": self._format_history_for_compaction(messages),
            },
        ]

        try:
            summary = ""
            usage = None
            async for event in self.client.chat_completion(
                compaction_messages,
                stream=False,
            ):
                if event.type == StreamEventType.TEXT_DELTA:
                    if event.text_delta and event.text_delta.content:
                        summary += event.text_delta.content
                if event.type == StreamEventType.ERROR:
                    self.last_error = str(event.error or "Compaction request failed.")
                    return None, None
                if event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage
                    if event.text_delta and event.text_delta.content:
                        summary += event.text_delta.content

            if not summary.strip() or not usage:
                if not summary.strip():
                    self.last_error = self.last_error or "Compaction response was empty."
                elif not usage:
                    self.last_error = self.last_error or "Compaction usage metadata was missing."
                return None, None

            return summary.strip(), usage

        except Exception as exc:
            self.last_error = str(exc)
            return None, None
