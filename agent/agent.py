from client.response import StreamEventType
from client.llm_client import LLMClient
from agent.events import AgentEvent
from typing import AsyncGenerator


class Agent:
    def __init__(self):
        self._client = LLMClient()

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:
        messages = [{"role": "user", "content": "Hello, how are you"}]
        async for event in self._client.chat_completion(messages, True):
            if event.type == StreamEventType.TEXT_DELTA:
                content = event.text_delta.content
                yield AgentEvent.text_delta(content)
            elif event.type == StreamEventType.MESSAGE_COMPLETE:
                yield AgentEvent.text_complete(content)
            elif event.type == StreamEventType.ERROR:
                yield AgentEvent.agent_error(
                    event.error or "Unknown error occurred",
                )
