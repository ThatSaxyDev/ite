from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from ite.tools.base import Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolMetadata, ToolResult, ToolRiskLevel


_READ_ONLY_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}


class HttpRequestParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(..., description="URL to request. Must start with http:// or https://")
    method: str = Field(
        "GET",
        description="HTTP method to use, for example GET, POST, PUT, PATCH, DELETE, or HEAD.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Optional request headers.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional query parameters to append to the URL.",
    )
    json_body: Any | None = Field(
        None,
        description="Optional JSON request body.",
        validation_alias=AliasChoices("json_body", "json"),
    )
    body: str | None = Field(
        None,
        description="Optional raw text request body.",
    )
    timeout: int = Field(
        30,
        ge=1,
        le=300,
        description="Request timeout in seconds.",
    )
    follow_redirects: bool = Field(
        True,
        description="Whether redirects should be followed automatically.",
    )

    @model_validator(mode="after")
    def _validate_payloads(self) -> "HttpRequestParams":
        if self.json_body is not None and self.body is not None:
            raise ValueError("Provide only one of json_body or body")
        method = self.method.strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError("Unsupported HTTP method")
        self.method = method
        return self


def _format_response_output(response: httpx.Response) -> tuple[str, bool]:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    truncated = False

    if "application/json" in content_type:
        try:
            text = json.dumps(response.json(), indent=2, ensure_ascii=False)
        except Exception:
            text = response.text
    elif content_type.startswith("text/") or content_type in {"application/xml", "application/javascript"}:
        text = response.text
    elif response.content:
        text = f"Binary response ({content_type or 'unknown content type'}, {len(response.content)} bytes)."
    else:
        text = ""

    max_size = 60 * 1024
    if len(text) > max_size:
        text = text[:max_size] + "\n... [truncated]"
        truncated = True
    return text, truncated


class HttpRequestTool(Tool):
    name = "http_request"
    description = "Make an HTTP request and return the response body with structured metadata."
    kind = ToolKind.NETWORK
    schema = HttpRequestParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        try:
            payload = HttpRequestParams(**params)
        except Exception:
            return True
        return payload.method not in _READ_ONLY_HTTP_METHODS

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        mutating = self.is_mutating(params)
        return ToolMetadata(
            mutating=mutating,
            risk_level=ToolRiskLevel.MEDIUM if mutating else ToolRiskLevel.LOW,
            allowed_in_plan_mode=not mutating,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = HttpRequestParams(**invocation.params)
        if params.method in _READ_ONLY_HTTP_METHODS:
            return None
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Send {params.method} request to {params.url}",
            command=f"{params.method} {params.url}",
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = HttpRequestParams(**invocation.params)
        parsed_url = urlparse(params.url)
        if parsed_url.scheme not in {"http", "https"}:
            return ToolResult.error_result("Invalid URL; url must start with http:// or https://")

        request_kwargs: dict[str, Any] = {
            "method": params.method,
            "url": params.url,
            "headers": params.headers,
            "params": params.params,
        }
        if params.json_body is not None:
            request_kwargs["json"] = params.json_body
        elif params.body is not None:
            request_kwargs["content"] = params.body

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(params.timeout),
                follow_redirects=params.follow_redirects,
                headers={"User-Agent": "ite-agent/http_request"},
            ) as client:
                response = await client.request(**request_kwargs)
        except Exception as exc:
            return ToolResult.error_result(f"Request failed: {exc}")

        output, truncated = _format_response_output(response)
        metadata = {
            "url": params.url,
            "method": params.method,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", "").split(";", 1)[0].strip(),
            "content_length": len(response.content),
            "response_headers": dict(response.headers),
            "intent": "http request",
        }

        if response.status_code >= 400:
            return ToolResult.error_result(
                f"HTTP {response.status_code} request failed.",
                output=output,
                truncated=truncated,
                metadata=metadata,
                exit_code=response.status_code,
            )

        return ToolResult.success_result(
            output or f"HTTP {response.status_code} with no response body.",
            truncated=truncated,
            metadata=metadata,
            exit_code=response.status_code,
        )
