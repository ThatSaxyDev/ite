"""Tool: head_to_head — analyze historical matchup data between two teams/players."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolMetadata, ToolResult, ToolRiskLevel


class HeadToHeadParams(BaseModel):
    team_a: str = Field(
        ...,
        description="First team or player name, e.g. 'Lakers' or 'Djokovic'",
    )
    team_b: str = Field(
        ...,
        description="Second team or player name, e.g. 'Celtics' or 'Alcaraz'",
    )
    sport: str = Field(
        ...,
        description="Sport name, e.g. 'NBA', 'NFL', 'Tennis', 'Soccer'",
    )
    last_n: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of recent matchups to analyze (default: 10, max: 50)",
    )


class HeadToHeadTool(Tool):
    name = "head_to_head"
    description = (
        "Analyze historical head-to-head results between two teams or players. "
        "Returns win/loss record, recent form, key stats from past matchups, "
        "and notable patterns. Critical for informed betting decisions."
    )
    kind = ToolKind.NETWORK
    schema = HeadToHeadParams

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
        params = HeadToHeadParams(**invocation.params)

        try:
            analysis = await self._analyze_h2h(
                params.team_a, params.team_b, params.sport, params.last_n
            )
            return ToolResult.success_result(
                analysis,
                metadata={
                    "team_a": params.team_a,
                    "team_b": params.team_b,
                    "sport": params.sport,
                    "matchups_analyzed": params.last_n,
                },
            )
        except Exception as e:
            return ToolResult.error_result(f"Head-to-head analysis failed: {e}")

    async def _analyze_h2h(
        self, team_a: str, team_b: str, sport: str, last_n: int
    ) -> str:
        """Search for and analyze head-to-head data.

        Uses web search to find recent H2H results, then fetches the most
        promising result page for detailed stats.
        """
        from ite.tools.builtin.web_search import WebSearchTool

        search_tool = WebSearchTool(self.config)

        query = f"{team_a} vs {team_b} head to head record last {last_n} games {sport}"
        search_result = await search_tool.execute(
            ToolInvocation(
                params={"query": query, "max_results": 5},
                cwd=self.config.cwd,
            )
        )

        output_lines = [
            f"## Head-to-Head: {team_a} vs {team_b} ({sport})",
            f"_Last {last_n} matchups_",
            "",
        ]

        if search_result.success:
            output_lines.append(search_result.output[:4000])
            output_lines.append("")
            output_lines.append("---")
            output_lines.append(
                "**Analysis tips:** Look for: home/away splits, recent form disparity, "
                "injuries affecting past results, stylistic matchup advantages, "
                "and whether the underdog has covered the spread historically."
            )
        else:
            output_lines.append(f"_Search failed: {search_result.error}_")

        return "\n".join(output_lines)
