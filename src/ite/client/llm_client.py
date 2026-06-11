from ite.config.config import Config
from ite.client.response import parse_tool_call_arguments
from ite.client.response import ToolCall
from ite.client.response import ToolCallDelta
from openai import APIError
from openai import APIConnectionError
import asyncio
import base64
import json
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
from ite.cloud import get_bundled_models
from ite.config.loader import load_saved_custom_provider
from ite import __version__
import httpx
from datetime import datetime

LEGACY_BUNDLED_MODEL_ALIASES: dict[str, str] = {
    "kimi-k2.5:cloud": "moonshotai/kimi-k2.5",
    "kimi-k2.6:cloud": "moonshotai/kimi-k2.6",
    "minimax-m2.5:cloud": "minimax/minimax-m2.5",
    "minimax-m2.7:cloud": "minimax/minimax-m2.7",
    "minimax-m3:cloud": "minimax/minimax-m3",
    "glm-5:cloud": "z-ai/glm-5",
    "glm-5.1:cloud": "z-ai/glm-5.1",
}

CLOUD_AGENT_MAX_TOKENS_DEFAULT = 4_096
CLOUD_AGENT_MAX_TOKENS_DEEPSEEK = 8_192
CLOUD_TEXT_MAX_TOKENS = 1_200


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
        if self._has_user_provider_credentials():
            return False
        source_kind = str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
        if source_kind == "bundled":
            return True
        if source_kind in {"saved", "custom"}:
            return False
        if self._current_model_has_saved_profile():
            return False
        model_name = str(self.config.model_name or "").strip()
        bundled_names = {
            str(item.get("model_name") or "").strip()
            for item in get_bundled_models(self.config)
        }
        return model_name in bundled_names

    def _has_user_provider_credentials(self) -> bool:
        return bool(
            str(self.config.base_url or "").strip()
            and str(self.config.api_key or "").strip()
        )

    def _current_model_has_saved_profile(self) -> bool:
        source_kind = str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
        if source_kind == "bundled":
            return False
        if source_kind == "saved":
            return True
        profiles = load_saved_custom_provider()
        if not isinstance(profiles, dict):
            return False
        model_name = str(self.config.model_name or "").strip()
        return model_name in profiles

    def _cloud_error_code(self, payload: dict[str, Any]) -> str:
        error = payload.get("error") or {}
        return str(error.get("code") or "").strip().lower()

    def _saved_provider_fallback(self) -> dict[str, str] | None:
        profiles = load_saved_custom_provider()
        if not profiles:
            return None

        if not isinstance(profiles, dict):
            return None

        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            model_name = str(profile.get("model_name") or "").strip()
            api_key = str(profile.get("api_key") or "").strip()
            base_url = str(profile.get("base_url") or "").strip()
            if not model_name or not api_key or not base_url:
                continue
            return {
                "model_name": model_name,
                "api_key": api_key,
                "base_url": base_url,
            }
        return None

    def _should_bypass_bundled_error(self, payload: dict[str, Any]) -> bool:
        if self._cloud_error_code(payload) not in {
            "entitlement_denied",
            "model_budget_exhausted",
            "model_rate_limited",
            "provider_not_configured",
        }:
            return False
        return self._saved_provider_fallback() is not None

    async def _activate_saved_provider_fallback(self) -> bool:
        fallback = self._saved_provider_fallback()
        if fallback is None:
            return False

        await self.close()
        self.config.model_name = fallback["model_name"]
        self.config.api_key = fallback["api_key"]
        self.config.base_url = fallback["base_url"]
        self.config.model.source_kind = "saved"
        return True

    def _resolve_cloud_model_name(self) -> str:
        model_name = str(self.config.model_name or "").strip()
        source_kind = str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
        if source_kind == "bundled":
            return LEGACY_BUNDLED_MODEL_ALIASES.get(model_name, model_name)
        return model_name

    def _cloud_agent_max_tokens(self, model_name: str) -> int:
        normalized = model_name.strip().lower()
        if "deepseek-v4" in normalized:
            return CLOUD_AGENT_MAX_TOKENS_DEEPSEEK
        return CLOUD_AGENT_MAX_TOKENS_DEFAULT

    def _cloud_inference_endpoint(self, session: Any) -> str:
        return f"{session.api_url.rstrip('/')}/inference/chat"

    def _cloud_headers(self, session: Any) -> dict[str, str]:
        return {
            "authorization": f"Bearer {session.access_token}",
            "content-type": "application/json",
            "accept": "application/x-ndjson, application/json",
            "user-agent": f"ite-agent/{__version__}",
            "x-ite-client": "terminal-runtime",
        }

    def _encoded_cloud_request_payload(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        encoded = base64.urlsafe_b64encode(
            json.dumps(request_payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        return {
            "payloadEncoding": "base64json",
            "payloadVersion": 1,
            "payload": encoded,
        }

    def _should_retry_plain_cloud_payload(
        self,
        *,
        status_code: int,
        payload: dict[str, Any],
    ) -> bool:
        if status_code != 400:
            return False
        error = payload.get("error") or {}
        if str(error.get("code") or "").strip().lower() != "invalid_request":
            return False
        details = error.get("details") or {}
        issues = details.get("issues") if isinstance(details, dict) else {}
        field_errors = issues.get("fieldErrors") if isinstance(issues, dict) else {}
        if not isinstance(field_errors, dict):
            return False
        return "model" in field_errors and "messages" in field_errors

    def _format_cloud_transport_error(self, exc: httpx.HTTPError, endpoint: str) -> str:
        return f"Could not reach iTE bundled inference at {endpoint}: {exc}"

    def _format_cloud_http_error(
        self,
        *,
        status_code: int,
        endpoint: str,
        payload: dict[str, Any],
        body: bytes,
    ) -> str:
        formatted = self._format_cloud_error(payload)
        if payload.get("error"):
            if formatted == "Bundled inference request failed.":
                return (
                    "Bundled inference request failed after reaching "
                    f"{endpoint} (HTTP {status_code})."
                )
            return formatted

        body_excerpt = body.decode("utf-8", errors="replace").strip()
        body_lower = body_excerpt.lower()
        if status_code == 403 and (
            "<title>blocked</title>" in body_lower
            or body_lower.startswith("<!doctype html")
        ):
            return (
                "iTE Cloud inference was blocked before it reached the API app "
                f"(HTTP 403 from {endpoint}). Server logs may not show "
                "`POST /inference/chat` for this request. Try again in a moment; "
                "if it keeps happening, the cloud host edge rules need to allow "
                "terminal inference POSTs."
            )
        if len(body_excerpt) > 240:
            body_excerpt = f"{body_excerpt[:240]}..."
        message = f"iTE Cloud inference returned HTTP {status_code} from {endpoint}."
        if body_excerpt:
            message = f"{message} Response: {body_excerpt}"
        return message

    def _format_cloud_error(self, payload: dict[str, Any]) -> str:
        error = payload.get("error") or {}
        details = error.get("details") or {}
        code = str(error.get("code") or "")
        message = str(error.get("message") or "Bundled inference request failed.")
        window = str(details.get("window") or "")
        reset_at = str(details.get("resetAt") or "")
        provider = str(details.get("provider") or "")
        provider_status = details.get("providerStatus")
        provider_ref = str(details.get("providerRef") or "")
        provider_message = str(details.get("providerMessage") or "")

        def _window_label(value: str) -> str:
            return {
                "five_hour": "5-hour window",
                "seven_day": "7-day window",
                "thirty_day": "30-day window",
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
                    f"Review usage in account billing, or use your own key or a local model for now."
                )
            return (
                f"Bundled usage is unavailable right now. "
                f"Your {window_label} is full. Review usage in account billing, "
                f"or use your own key or a local model for now."
            )

        if code == "entitlement_denied":
            return (
                "This account does not have bundled model access yet. "
                "Visit /pricing to start iTE Pro, or run `/setup` to connect your own model provider."
            )

        if code == "provider_not_configured":
            return (
                "Bundled usage is not available yet for this model. "
                "Run `/setup` to connect your own model provider, or use a local model for now."
            )

        if code == "model_rate_limited":
            return (
                "Too many bundled request round-trips happened in the current hourly pace window. "
                "Your central usage balance is separate."
            )

        if code == "model_budget_exhausted":
            reset_label = _format_reset(reset_at, "five_hour")
            reset_copy = (
                f" The current window resets {reset_label}."
                if reset_label
                else ""
            )
            return (
                "Bundled usage is unavailable right now. "
                f"Switch to a cheaper bundled model, wait for the shared usage window to reset, or use your own key.{reset_copy}"
            )

        if code == "model_output_limited":
            max_tokens = details.get("maxOutputTokens")
            requested = details.get("requestedMaxTokens")
            if max_tokens:
                return (
                    f"This bundled model is capped at {max_tokens} output tokens per request. "
                    f"Requested {requested or 'more than the policy allows'}. "
                    "Lower the output limit or use your own key."
                )
            return (
                "This bundled model has a lower output-token cap. "
                "Lower the output limit or use your own key."
            )

        if code == "provider_request_failed":
            parts = ["Bundled inference provider failed"]
            if provider:
                parts.append(f"({provider})")
            if provider_status:
                parts.append(f"with status {provider_status}")
            message_text = " ".join(parts) + "."
            if provider_ref:
                message_text += f" Ref: {provider_ref}."
            if provider_message:
                message_text += f" {provider_message}"
            message_text += " Try again in a moment, or use your own key or a local model for now."
            return message_text

        if code == "internal_error":
            return (
                "Bundled usage is temporarily unavailable right now. "
                "Try again in a moment, or use your own key or a local model for now."
            )

        if window:
            window_label = _window_label(window)
            return f"{message} ({window_label})"

        return message

    def _is_retryable_cloud_failure(
        self,
        *,
        response_status: int | None = None,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> bool:
        if error is not None:
            return isinstance(
                error,
                (
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                    httpx.TimeoutException,
                ),
            )

        payload = payload or {}
        error_payload = payload.get("error") or {}
        details = error_payload.get("details") or {}
        code = str(error_payload.get("code") or "").strip().lower()
        provider_status = details.get("providerStatus")
        provider_message = str(details.get("providerMessage") or "").lower()

        if code in {"provider_request_failed", "internal_error", "provider_unavailable"}:
            if isinstance(provider_status, int) and provider_status in {500, 502, 503, 504}:
                return True
            if response_status in {500, 502, 503, 504}:
                return True
            if any(marker in provider_message for marker in ("temporarily unavailable", "timeout", "connection", "try again")):
                return True

        return False

    async def _post_cloud_inference(
        self,
        session: Any,
        request_payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        max_attempts = min(self._max_retries + 1, 3)
        last_error: Exception | None = None
        use_encoded_payload = True

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    response = await client.post(
                        self._cloud_inference_endpoint(session),
                        headers=self._cloud_headers(session),
                        json=self._encoded_cloud_request_payload(request_payload)
                        if use_encoded_payload
                        else request_payload,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < (max_attempts - 1) and self._is_retryable_cloud_failure(error=exc):
                    await asyncio.sleep(2**attempt)
                    continue
                raise

            try:
                payload = response.json()
            except ValueError:
                payload = {}

            if (
                use_encoded_payload
                and self._should_retry_plain_cloud_payload(
                    status_code=response.status_code,
                    payload=payload,
                )
            ):
                use_encoded_payload = False
                continue

            if (
                (response.status_code != 200 or not payload.get("ok"))
                and attempt < (max_attempts - 1)
                and self._is_retryable_cloud_failure(
                    response_status=response.status_code,
                    payload=payload,
                )
            ):
                await asyncio.sleep(2**attempt)
                continue

            return response.status_code, payload

        if last_error is not None:
            raise last_error
        return 502, {}

    async def _stream_cloud_inference_events(
        self,
        session: Any,
        request_payload: dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        endpoint = self._cloud_inference_endpoint(session)
        max_attempts = min(self._max_retries + 1, 3)
        last_error: httpx.HTTPError | None = None
        use_encoded_payload = True

        for attempt in range(max_attempts):
            emitted_event = False
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        headers=self._cloud_headers(session),
                        json=self._encoded_cloud_request_payload(request_payload)
                        if use_encoded_payload
                        else request_payload,
                    ) as response:
                        if response.status_code != 200:
                            body = await response.aread()
                            try:
                                payload = json.loads(body.decode("utf-8"))
                            except (ValueError, UnicodeDecodeError):
                                payload = {}
                            if (
                                use_encoded_payload
                                and self._should_retry_plain_cloud_payload(
                                    status_code=response.status_code,
                                    payload=payload,
                                )
                            ):
                                use_encoded_payload = False
                                continue
                            if (
                                attempt < (max_attempts - 1)
                                and self._is_retryable_cloud_failure(
                                    response_status=response.status_code,
                                    payload=payload,
                                )
                            ):
                                await asyncio.sleep(2**attempt)
                                continue
                            yield StreamEvent(
                                type=StreamEventType.ERROR,
                                error=self._format_cloud_http_error(
                                    status_code=response.status_code,
                                    endpoint=endpoint,
                                    payload=payload,
                                    body=body,
                                ),
                                error_payload=payload,
                            )
                            return

                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            event_type = str(event.get("type") or "")

                            if event_type == "text_delta":
                                content = str(event.get("content") or "")
                                if content:
                                    emitted_event = True
                                    yield StreamEvent(
                                        type=StreamEventType.TEXT_DELTA,
                                        text_delta=TextDelta(content=content),
                                    )
                                continue

                            if event_type == "tool_call_start":
                                emitted_event = True
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_START,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=str(event.get("id") or ""),
                                        name=str(event.get("name") or ""),
                                    ),
                                )
                                continue

                            if event_type == "tool_call_delta":
                                emitted_event = True
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_DELTA,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=str(event.get("id") or ""),
                                        name=str(event.get("name") or ""),
                                        arguments_delta=str(event.get("argumentsDelta") or ""),
                                    ),
                                )
                                continue

                            if event_type == "tool_call_complete":
                                emitted_event = True
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_COMPLETE,
                                    tool_call=ToolCall(
                                        call_id=str(event.get("id") or ""),
                                        name=str(event.get("name") or ""),
                                        arguments=parse_tool_call_arguments(str(event.get("arguments") or "{}")),
                                    ),
                                )
                                continue

                            if event_type == "message_complete":
                                usage_payload = event.get("usage") or {}
                                if not isinstance(usage_payload, dict):
                                    usage_payload = {}
                                quotas_payload = event.get("quotas")
                                usage_summary = (
                                    {"quotas": quotas_payload}
                                    if isinstance(quotas_payload, dict)
                                    else None
                                )
                                usage = TokenUsage(
                                    prompt_tokens=int(usage_payload.get("promptTokens") or 0),
                                    completion_tokens=int(usage_payload.get("completionTokens") or 0),
                                    total_tokens=int(usage_payload.get("totalTokens") or 0),
                                    cached_tokens=0,
                                )
                                reasoning_content = event.get("reasoningContent")
                                emitted_event = True
                                yield StreamEvent(
                                    type=StreamEventType.MESSAGE_COMPLETE,
                                    finish_reason=str(event.get("finishReason") or "stop"),
                                    usage=usage,
                                    usage_summary=usage_summary,
                                    reasoning_content=str(reasoning_content) if reasoning_content else None,
                                )
                                continue

                            if event_type == "error":
                                error_payload = event.get("error")
                                payload = {
                                    "error": error_payload if isinstance(error_payload, dict) else {}
                                }
                                error_text = self._format_cloud_error(payload)
                                if error_text == "Bundled inference request failed.":
                                    error_text = (
                                        "Bundled inference request failed after reaching "
                                        f"{endpoint}."
                                    )
                                emitted_event = True
                                yield StreamEvent(
                                    type=StreamEventType.ERROR,
                                    error=error_text,
                                    error_payload=payload,
                                )
                                return
                    return
            except httpx.HTTPError as exc:
                last_error = exc
                if (
                    not emitted_event
                    and attempt < (max_attempts - 1)
                    and self._is_retryable_cloud_failure(error=exc)
                ):
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        if last_error is not None:
            raise last_error

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
        visual_budget: int | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        if self._is_cloud_model():
            async for event in self._cloud_chat_completion(
                messages, tools=tools, visual_budget=visual_budget
            ):
                yield event
            return

        client = self.get_client()
        safe_messages = self._sanitize_messages(messages)

        kwargs = {
            "model": self.config.model_name,
            "messages": safe_messages,
            "stream": stream,
        }
        if self.config.model_name == "gemma4:31b-cloud":
            kwargs["temperature"] = 1.0
            kwargs["extra_body"] = {
                "top_p": 0.95,
                "top_k": 64,
            }
        
        if visual_budget:
            if "extra_body" not in kwargs:
                kwargs["extra_body"] = {}
            kwargs["extra_body"]["visual_token_budget"] = visual_budget

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
            except httpx.ReadTimeout:
                if attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=format_provider_error(
                            kind="timeout",
                            message="The request timed out while streaming. Try again.",
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

    async def complete_text(
        self,
        messages: list[dict[str, Any]],
    ) -> str:
        if self._is_cloud_model():
            return await self._cloud_complete_text(messages)

        client = self.get_client()
        safe_messages = self._sanitize_messages(messages)
        kwargs = {
            "model": self.config.model_name,
            "messages": safe_messages,
            "stream": False,
        }

        for attempt in range(self._max_retries + 1):
            try:
                event = await self._non_stream_response(client, kwargs)
                text = (event.text_delta.content if event.text_delta else "").strip()
                if text:
                    return text
                raise ValueError("Commit subject generation returned an empty response.")
            except ValueError:
                raise
            except RateLimitError as e:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    format_provider_error(
                        kind="rate_limit",
                        message=str(e),
                        model_name=self.config.model_name,
                        base_url=self.config.base_url,
                    )
                ) from e
            except APIConnectionError as e:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    format_provider_error(
                        kind="connection",
                        message=str(e),
                        model_name=self.config.model_name,
                        base_url=self.config.base_url,
                    )
                ) from e
            except httpx.ReadTimeout as e:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    format_provider_error(
                        kind="timeout",
                        message="The request timed out while streaming. Try again.",
                        model_name=self.config.model_name,
                        base_url=self.config.base_url,
                    )
                ) from e
            except APIError as e:
                status_code = getattr(e, "status_code", None)
                is_server_error = isinstance(status_code, int) and status_code >= 500
                if is_server_error and attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    format_provider_error(
                        kind="api",
                        message=str(e),
                        status_code=status_code,
                        model_name=self.config.model_name,
                        base_url=self.config.base_url,
                    )
                ) from e

        raise RuntimeError("Commit subject generation failed.")

    async def _cloud_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        visual_budget: int | None = None,
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
        request_payload: dict[str, Any] = {
            "model": model_name,
            "messages": safe_messages,
            "maxTokens": self._cloud_agent_max_tokens(model_name),
            "temperature": self.config.temperature,
            "stream": True,
        }
        if self.config.model_name == "gemma4:31b-cloud":
            request_payload["temperature"] = 1.0
            request_payload["top_p"] = 0.95
            request_payload["top_k"] = 64
        
        if visual_budget:
            request_payload["visual_token_budget"] = visual_budget

        if tools:
            request_payload["tools"] = self._build_tools(tools)
            request_payload["toolChoice"] = "auto"

        try:
            async for event in self._stream_cloud_inference_events(
                session, request_payload
            ):
                if (
                    event.type == StreamEventType.ERROR
                    and self._should_bypass_bundled_error(event.error_payload or {})
                    and await self._activate_saved_provider_fallback()
                ):
                    async for fallback_event in self.chat_completion(
                        messages, tools=tools, visual_budget=visual_budget
                    ):
                        yield fallback_event
                    return
                yield event
            return
        except httpx.HTTPError as exc:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=self._format_cloud_transport_error(
                    exc, self._cloud_inference_endpoint(session)
                ),
            )
            return

    async def _cloud_complete_text(self, messages: list[dict[str, Any]]) -> str:
        session = get_cloud_session(self.config)
        if session is None:
            raise RuntimeError(
                "Cloud session is missing or expired. Run `/cloud login` and try again."
            )

        safe_messages = self._sanitize_messages(messages)
        model_name = self._resolve_cloud_model_name()
        request_payload: dict[str, Any] = {
            "model": model_name,
            "messages": safe_messages,
            "maxTokens": CLOUD_TEXT_MAX_TOKENS,
            "temperature": self.config.temperature,
        }

        try:
            status_code, payload = await self._post_cloud_inference(
                session, request_payload
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                self._format_cloud_transport_error(
                    exc, self._cloud_inference_endpoint(session)
                )
            ) from exc

        if status_code != 200 or not payload.get("ok"):
            if await self._activate_saved_provider_fallback() if self._should_bypass_bundled_error(payload) else False:
                return await self.complete_text(messages)
            raise RuntimeError(self._format_cloud_error(payload))

        output = str(payload.get("output") or "").strip()
        if not output:
            raise ValueError("Commit subject generation returned an empty response.")
        return output

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize outbound messages so providers never receive null content."""
        sanitized: list[dict[str, Any]] = []
        preserve_reasoning_content = self._should_preserve_reasoning_content()
        for raw in messages or []:
            role = str(raw.get("role") or "").strip()
            if not role:
                continue

            msg: dict[str, Any] = {"role": role}
            content = raw.get("content")
            if role in ("user", "tool") and isinstance(content, list):
                # Preserve multimodal user/tool content parts.
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

            if (
                preserve_reasoning_content
                and role == "assistant"
                and raw.get("reasoning_content") is not None
            ):
                msg["reasoning_content"] = str(raw.get("reasoning_content") or "")

            sanitized.append(msg)
        return sanitized

    def _should_preserve_reasoning_content(self) -> bool:
        """DeepSeek V4 thinking-mode tool turns must replay reasoning_content."""
        model_name = str(self.config.model_name or "").strip().lower()
        base_url = str(self.config.base_url or "").strip().lower()
        if "deepseek-reasoner" in model_name:
            return False
        return "deepseek-v4" in model_name or "api.deepseek.com" in base_url

    async def _stream_response(
        self,
        client: AsyncOpenAI,
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        response = await client.chat.completions.create(**kwargs)

        finish_reason: str | None = None
        usage: TokenUsage | None = None
        tool_calls: dict[int, dict[str, Any]] = {}
        reasoning_parts: list[str] = []

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

            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                reasoning_parts.append(str(reasoning_delta))

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
            reasoning_content="".join(reasoning_parts) or None,
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
        reasoning_content = getattr(message, "reasoning_content", None)

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
            reasoning_content=str(reasoning_content) if reasoning_content else None,
            finish_reason=choice.finish_reason,
            usage=usage,
        )
