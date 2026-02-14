import httpx
from urllib.parse import urlparse
from tools.base import ToolResult, ToolInvocation, ToolKind, Tool
from pydantic import BaseModel, Field


class WebFetchParams(BaseModel):
    url: str = Field(..., description="URL to fetch (must be http:// or https://)")
    timeout: int = Field(
        30,
        ge=5,
        le=120,
        description="Request timeout in seconds (default: 120)",
    )


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch the content of a web page. Returns the content of the web page"
    kind = ToolKind.NETWORK
    schema = WebFetchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebFetchParams(**invocation.params)

        parsed_url = urlparse(params.url)

        if not parsed_url.scheme or parsed_url.scheme not in ["http", "https"]:
            return ToolResult.error_result(
                "Invalid URL; url must start with http:// or https://"
            )

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(params.timeout),
                follow_redirects=True,
            ) as client:
                response = await client.get(params.url)
                response.raise_for_status()
                text = response.text
        except httpx.HTTPStatusError as e:
            return ToolResult.error_result(
                f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
            )

        except Exception as e:
            return ToolResult.error_result(f"Request failed: {e}")

        if len(text) > 100 * 1024:
            text = text[: 100 * 1024] + "\n... [truncated]"

        return ToolResult.success_result(
            text,
            metadata={
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_length": len(response.content),
            },
        )
