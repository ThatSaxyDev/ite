import httpx
import html2text
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from tools.base import ToolResult, ToolInvocation, ToolKind, Tool
from pydantic import BaseModel, Field


class WebFetchParams(BaseModel):
    url: str = Field(..., description="URL to fetch (must be http:// or https://)")
    timeout: int = Field(
        30,
        ge=5,
        le=120,
        description="Request timeout in seconds (default: 30)",
    )


# Tags that add noise and no useful content
_STRIP_TAGS = {
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "iframe",
    "svg",
    "form",
    "button",
}


def _html_to_markdown(html: str) -> str:
    """Convert raw HTML to clean, readable markdown."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy tags entirely
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Prefer main content containers if available
    main_content = (
        soup.find("main") or soup.find("article") or soup.find("div", {"role": "main"})
    )
    target_html = str(main_content) if main_content else str(soup)

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0  # No wrapping
    converter.skip_internal_links = True
    converter.inline_links = True
    converter.protect_links = True

    markdown = converter.handle(target_html)

    # Collapse excessive blank lines
    lines = markdown.splitlines()
    cleaned = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch the content of a web page. Returns cleaned, readable text extracted from the page."
    kind = ToolKind.NETWORK
    schema = WebFetchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebFetchParams(**invocation.params)

        parsed_url = urlparse(params.url)

        if not parsed_url.scheme or parsed_url.scheme not in ["http", "https"]:
            return ToolResult.error_result(
                "Invalid URL; url must start with http:// or https://"
            )

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ite/0.1; +https://github.com)",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(params.timeout),
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = await client.get(params.url)
                response.raise_for_status()
                raw_text = response.text
        except httpx.HTTPStatusError as e:
            return ToolResult.error_result(
                f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
            )

        except Exception as e:
            return ToolResult.error_result(f"Request failed: {e}")

        content_type = response.headers.get("content-type", "")

        # JSON or plain text — return as-is, no conversion needed
        if "application/json" in content_type or "text/plain" in content_type:
            text = raw_text
        else:
            # HTML — convert to clean markdown
            text = _html_to_markdown(raw_text)

        # Truncate if still too large
        max_size = 60 * 1024  # 60KB
        truncated = False
        if len(text) > max_size:
            text = text[:max_size] + "\n... [truncated]"
            truncated = True

        return ToolResult.success_result(
            text,
            truncated=truncated,
            metadata={
                "status_code": response.status_code,
                "content_type": content_type.split(";")[0].strip(),
                "content_length": len(response.content),
            },
        )
