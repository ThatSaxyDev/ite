from ite.config.config import Config
from ite.client.response import parse_tool_call_arguments
from ite.client.response import ToolCall
from ite.client.response import ToolCallDelta
from openai import APIError
from openai import APIConnectionError
import asyncio
from openai import RateLimitError
from typing import AsyncGenerator
from ite.client.response import StreamEventType
from ite.client.response import StreamEvent
from ite.client.response import TokenUsage
from ite.client.response import TextDelta
from typing import Any
from openai import AsyncOpenAI


class LLMClient:
    def __init__(self, config: Config) -> None:
        self._client: AsyncOpenAI | None = None
        self._max_retries: int = 3
        self.config = config

    def get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=300.0,  # 5 min — streaming can be slow
                max_retries=0,  # we handle retries ourselves
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _build_tools(self, tools: list[dict[str, Any]]):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "parameters",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    ),
                },
            }
            for tool in tools
        ]

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[StreamEvent, None]:
        client = self.get_client()
        safe_messages = self._sanitize_messages(messages)

        kwargs = {
            "model": self.config.model_name,
            "messages": safe_messages,
            "stream": stream,
        }

        if stream:
            kwargs["stream_options"] = {"include_usage": True}

        if tools:
            kwargs["tools"] = self._build_tools(tools)
            kwargs["tool_choice"] = "auto"

        for attempt in range(self._max_retries + 1):
            try:
                if stream:
                    async for event in self._stream_response(client, kwargs):
                        yield event
                else:
                    event = await self._non_stream_response(client, kwargs)
                yield event
                return
            except RateLimitError as e:
                if attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Rate limit exceeded: {e}",
                    )
                    return
            except APIConnectionError as e:
                if attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"API connection error: {e}",
                    )
                    return
            except APIError as e:
                status_code = getattr(e, "status_code", None)
                is_server_error = isinstance(status_code, int) and status_code >= 500
                if is_server_error and attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                    continue
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"API error: {e}",
                )
                return

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize outbound messages so providers never receive null content."""
        sanitized: list[dict[str, Any]] = []
        for raw in messages or []:
            role = str(raw.get("role") or "").strip()
            if not role:
                continue

            msg: dict[str, Any] = {"role": role}
            content = raw.get("content")

            # OpenAI-compatible providers can reject missing/null content.
            # Keep content consistently string-typed for all roles.
            msg["content"] = "" if content is None else str(content)

            tool_call_id = raw.get("tool_call_id")
            if tool_call_id is not None:
                msg["tool_call_id"] = str(tool_call_id)

            tool_calls = raw.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                cleaned_calls: list[dict[str, Any]] = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    call_id = str(call.get("id") or "")
                    call_type = str(call.get("type") or "function")
                    fn = call.get("function") or {}
                    if not isinstance(fn, dict):
                        fn = {}
                    fn_name = str(fn.get("name") or "")
                    fn_args = fn.get("arguments")
                    if fn_args is None:
                        fn_args = "{}"
                    cleaned_calls.append(
                        {
                            "id": call_id,
                            "type": call_type,
                            "function": {
                                "name": fn_name,
                                "arguments": str(fn_args),
                            },
                        }
                    )
                if cleaned_calls:
                    msg["tool_calls"] = cleaned_calls

            sanitized.append(msg)
        return sanitized

    async def _stream_response(
        self,
        client: AsyncOpenAI,
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        response = await client.chat.completions.create(**kwargs)

        finish_reason: str | None = None
        usage: TokenUsage | None = None
        tool_calls: dict[int, dict[str, Any]] = {}

        async for chunk in response:
            if hasattr(chunk, "usage") and chunk.usage:
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                    total_tokens=chunk.usage.total_tokens or 0,
                    cached_tokens=getattr(details, "cached_tokens", 0) or 0,
                )

            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            if delta.content:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(content=delta.content),
                )

            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx = tool_call_delta.index

                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tool_call_delta.id or "",
                            "name": "",
                            "arguments": "",
                            "start_emitted": False,
                        }

                    tc = tool_calls[idx]

                    # Some providers stream id/name/arguments across multiple chunks.
                    if tool_call_delta.id and not tc["id"]:
                        tc["id"] = tool_call_delta.id

                    if tool_call_delta.function:
                        if tool_call_delta.function.name and not tc["name"]:
                            tc["name"] = tool_call_delta.function.name

                        if tc["name"] and not tc["start_emitted"]:
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_START,
                                tool_call_delta=ToolCallDelta(
                                    call_id=tc["id"],
                                    name=tc["name"],
                                ),
                            )
                            tc["start_emitted"] = True

                        if tool_call_delta.function.arguments:
                            tc["arguments"] += tool_call_delta.function.arguments
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_DELTA,
                                tool_call_delta=ToolCallDelta(
                                    call_id=tc["id"],
                                    name=tc["name"] or tool_call_delta.function.name,
                                    arguments_delta=tool_call_delta.function.arguments,
                                ),
                            )

        for idx, tc in tool_calls.items():
            call_id = tc["id"] or f"call_{idx}"
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id=call_id,
                    name=tc["name"] or "tool",
                    arguments=parse_tool_call_arguments(tc["arguments"]),
                ),
            )

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def _non_stream_response(
        self,
        client: AsyncOpenAI,
        kwargs: dict[str, Any],
    ) -> StreamEvent:
        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        text_delta = None

        if message.content:
            text_delta = TextDelta(content=message.content)

        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        call_id=tc.id,
                        name=tc.function.name,
                        arguments=parse_tool_call_arguments(tc.function.arguments),
                    ),
                )

        usage = None

        if response.usage:
            details = getattr(response.usage, "prompt_tokens_details", None)
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
                cached_tokens=getattr(details, "cached_tokens", 0) or 0,
            )

        return StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            text_delta=text_delta,
            finish_reason=choice.finish_reason,
            usage=usage,
        )
