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
from ite.utils.errors import format_provider_error
from ite.cloud import get_cloud_session
import httpx
from datetime import datetime


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

    def _is_cloud_model(self) -> bool:
        return self.config.model_name.endswith(":cloud")

    def _resolve_cloud_model_name(self) -> str:
        model_name = self.config.model_name.removesuffix(":cloud")
        aliases = {
            "minimax-m2.5": "minimax-m2.7",
            "minimax-m2.7": "minimax-m2.7",
            "kimi-k2.5": "kimi-k2.5",
            "glm-5": "glm-5",
        }
        return aliases.get(model_name, model_name)

    def _format_cloud_error(self, payload: dict[str, Any]) -> str:
        error = payload.get("error") or {}
        details = error.get("details") or {}
        code = str(error.get("code") or "")
        message = str(error.get("message") or "Bundled inference request failed.")
        window = str(details.get("window") or "")
        reset_at = str(details.get("resetAt") or "")

        def _window_label(value: str) -> str:
            return {
                "five_hour": "5-hour window",
                "seven_day": "7-day window",
            }.get(value, "current usage window")

        def _format_reset(value: str, window_name: str) -> str | None:
            if not value:
                return None
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
            except ValueError:
                return None

            if window_name == "five_hour":
                return dt.strftime("%-I:%M%p").lower()
            return dt.strftime("%B %-d at %-I:%M%p").lower()

        if code == "quota_exhausted":
            window_label = _window_label(window)
            reset_label = _format_reset(reset_at, window)
            if reset_label:
                return (
                    f"Bundled usage is unavailable right now. "
                    f"Your {window_label} is full and resets {reset_label}. "
                    f"Use your own key or a local model for now."
                )
            return (
                f"Bundled usage is unavailable right now. "
                f"Your {window_label} is full. Use your own key or a local model for now."
            )

        if window:
            window_label = _window_label(window)
            return f"{message} ({window_label})"

        return message

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
        if self._is_cloud_model():
            async for event in self._cloud_chat_completion(messages, tools=tools):
                yield event
            return

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
                        error=format_provider_error(
                            kind="rate_limit",
                            message=str(e),
                            model_name=self.config.model_name,
                            base_url=self.config.base_url,
                        ),
                    )
                    return
            except APIConnectionError as e:
                if attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=format_provider_error(
                            kind="connection",
                            message=str(e),
                            model_name=self.config.model_name,
                            base_url=self.config.base_url,
                        ),
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
                    error=format_provider_error(
                        kind="api",
                        message=str(e),
                        status_code=status_code,
                        model_name=self.config.model_name,
                        base_url=self.config.base_url,
                    ),
                )
                return

    async def _cloud_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        session = get_cloud_session(self.config)
        if session is None:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error="Cloud session is missing or expired. Run `/cloud login` and try again.",
            )
            return

        safe_messages = self._sanitize_messages(messages)
        model_name = self._resolve_cloud_model_name()

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{session.api_url.rstrip('/')}/inference/chat",
                    headers={
                        "authorization": f"Bearer {session.access_token}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": safe_messages,
                        "tools": self._build_tools(tools) if tools else None,
                        "toolChoice": "auto" if tools else None,
                        "maxTokens": 1200,
                        "temperature": self.config.temperature,
                    },
                )
        except httpx.HTTPError as exc:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=f"Could not reach iTE bundled inference: {exc}",
            )
            return

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code != 200 or not payload.get("ok"):
            message = self._format_cloud_error(payload)
            yield StreamEvent(type=StreamEventType.ERROR, error=message)
            return

        output = str(payload.get("output") or "")
        if output:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content=output),
            )

        for tc in payload.get("toolCalls") or []:
            if not isinstance(tc, dict):
                continue
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id=str(tc.get("id") or ""),
                    name=str(tc.get("name") or ""),
                    arguments=parse_tool_call_arguments(str(tc.get("arguments") or "{}")),
                ),
            )

        usage_payload = payload.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(usage_payload.get("promptTokens") or 0),
            completion_tokens=int(usage_payload.get("completionTokens") or 0),
            total_tokens=int(usage_payload.get("totalTokens") or 0),
            cached_tokens=0,
        )

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason="stop",
            usage=usage,
        )

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize outbound messages so providers never receive null content."""
        sanitized: list[dict[str, Any]] = []
        for raw in messages or []:
            role = str(raw.get("role") or "").strip()
            if not role:
                continue

            msg: dict[str, Any] = {"role": role}
            content = raw.get("content")
            if role == "user" and isinstance(content, list):
                # Preserve multimodal user content parts.
                msg["content"] = content
            else:
                # OpenAI-compatible providers can reject missing/null content.
                # Keep non-multimodal content consistently string-typed.
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
