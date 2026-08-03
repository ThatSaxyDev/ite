"""Tool: fetch_odds — retrieve current betting odds for a sports matchup."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolMetadata, ToolResult, ToolRiskLevel


class FetchOddsParams(BaseModel):
    sport: str = Field(
        ...,
        description="Sport name, e.g. 'NBA', 'NFL', 'EPL', 'UFC'",
    )
    matchup: str = Field(
        ...,
        description="Matchup description, e.g. 'Lakers vs Celtics' or 'Man City vs Arsenal'",
    )
    market: str = Field(
        default="moneyline",
        description="Betting market: 'moneyline', 'spread', 'totals', 'props' (default: moneyline)",
    )


class FetchOddsTool(Tool):
    name = "fetch_odds"
    description = (
        "Retrieve current betting odds for a sports matchup. "
        "Returns moneyline, spread, and totals from major sportsbooks. "
        "Use this before making any betting recommendation."
    )
    kind = ToolKind.NETWORK
    schema = FetchOddsParams

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
        params = FetchOddsParams(**invocation.params)

        try:
            odds_data = await self._fetch_odds(params.sport, params.matchup, params.market)
            return ToolResult.success_result(
                odds_data,
                metadata={
                    "sport": params.sport,
                    "matchup": params.matchup,
                    "market": params.market,
                    "source": "odds_api",
                },
            )
        except Exception as e:
            return ToolResult.error_result(f"Failed to fetch odds: {e}")

    async def _fetch_odds(self, sport: str, matchup: str, market: str) -> str:
        """Fetch odds from the configured odds provider.

        Currently uses web_search + web_fetch to pull live data.
        Future: integrate with The Odds API (the-odds-api.com) for
        structured, real-time odds data.
        """
        from ite.tools.builtin.web_search import WebSearchTool
        from ite.tools.builtin.web_fetch import WebFetchTool

        search_tool = WebSearchTool(self.config)

        query = f"{matchup} {sport} betting odds {market} today"
        search_result = await search_tool.execute(
            ToolInvocation(
                params={"query": query, "max_results": 3},
                cwd=self.config.cwd,
            )
        )

        output_lines = [f"## Odds for {matchup} ({sport}) — {market.upper()}", ""]

        if search_result.success:
            output_lines.append(search_result.output[:3000])
            output_lines.append("")
            output_lines.append("---")
            output_lines.append(
                "**Note:** These results are scraped from search. "
                "For production use, integrate with The Odds API "
                "(https://the-odds-api.com) for real-time structured odds data "
                "including opening lines, live movement, and sharp action indicators."
            )
        else:
            output_lines.append(f"_Odds lookup failed: {search_result.error}_")
            output_lines.append("")
            output_lines.append(
                "**Fallback:** Use `web_search` to manually research current odds "
                f"for {matchup}."
            )

        return "\n".join(output_lines)
