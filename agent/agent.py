from __future__ import annotations
from agent.events import AgentEventType
from client.response import StreamEventType
from client.llm_client import LLMClient
from agent.events import AgentEvent
from typing import AsyncGenerator


class Agent:
    def __init__(self):
        self._client = LLMClient()

    async def run(self, message: str):
        yield AgentEvent.agent_start(message)
        # add user message to context

        final_response: str | None = None

        async for event in self._agentic_loop():
            yield event

            if event.type == AgentEventType.TEXT_COMPLETE:
                final_response = event.data.get("content")

        yield AgentEvent.agent_end(final_response)

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:
        messages = [{"role": "user", "content": "Hello, how are you"}]

        response_text = ""

        async for event in self._client.chat_completion(messages, True):
            if event.type == StreamEventType.TEXT_DELTA:
                if event.text_delta:
                    content = event.text_delta.content
                    response_text += content
                    yield AgentEvent.text_delta(content)
            elif event.type == StreamEventType.ERROR:
                yield AgentEvent.agent_error(
                    event.error or "Unknown error occurred",
                )

        if response_text:
            yield AgentEvent.text_complete(response_text)

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ) -> None:
        if self._client:
            await self._client.close()
            self._client = None
