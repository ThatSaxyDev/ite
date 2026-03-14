from ite.tools.base import ToolResult, ToolInvocation, ToolKind, Tool
from ite.tools.base import ToolMetadata, ToolRiskLevel
from pydantic import BaseModel, Field
try:
    from ddgs import DDGS
except Exception:  # pragma: no cover - fallback for older installs
    from duckduckgo_search import DDGS


class WebSearchParams(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(
        10,
        ge=1,
        le=20,
        description="Maximum results to return (default: 10)",
    )


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information. Returns search results with titles, URLs and snippets"
    kind = ToolKind.NETWORK
    schema = WebSearchParams

    def is_mutating(self, params: dict) -> bool:
        return False

    def get_metadata(self, params: dict) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebSearchParams(**invocation.params)

        try:
            results = DDGS().text(
                params.query,
                region="us-en",
                safesearch="off",
                timelimit="y",
                page=1,
                backend="auto",
                max_results=params.max_results,
            )

        except Exception as e:
            return ToolResult.error_result(f"Search failed: {e}")

        if not results:
            return ToolResult.success_result(
                f"No results found found for: {params.query}",
                metadata={
                    "query": params.query,
                    "results": 0,
                    "provider": "duckduckgo",
                },
            )

        output_lines = [f"Search results for: {params.query}"]

        for i, result in enumerate(results[: params.max_results], start=1):
            output_lines.append(f"{i}. Title: {result['title']}")
            output_lines.append(f"  URL: {result['href']}")
            if result.get("body"):
                output_lines.append(f"  Snippet: {result['body']}")
            output_lines.append("")

        top_urls = [
            str(result.get("href", "")).strip()
            for result in results[: params.max_results]
            if str(result.get("href", "")).strip()
        ]
        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={
                "query": params.query,
                "results": min(len(results), params.max_results),
                "provider": "duckduckgo",
                "top_urls": top_urls[:3],
                "intent": "external research",
            },
        )
