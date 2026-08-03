"""Tool: injury_report — get current injury status for a team or player."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolMetadata, ToolResult, ToolRiskLevel


class InjuryReportParams(BaseModel):
    team: str = Field(
        ...,
        description="Team or player name, e.g. 'Lakers' or 'Luka Doncic'",
    )
    sport: str = Field(
        default="",
        description="Sport name, e.g. 'NBA', 'NFL', 'EPL'. Auto-detected if empty.",
    )


class InjuryReportTool(Tool):
    name = "injury_report"
    description = (
        "Get the current injury report for a team or player. "
        "Returns active injuries, expected return dates, player status "
        "(out/questionable/probable), and impact analysis. "
        "Essential for evaluating true matchup strength."
    )
    kind = ToolKind.NETWORK
    schema = InjuryReportParams

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
        params = InjuryReportParams(**invocation.params)

        try:
            report = await self._get_injury_report(params.team, params.sport)
            return ToolResult.success_result(
                report,
                metadata={
                    "team": params.team,
                    "sport": params.sport,
                },
            )
        except Exception as e:
            return ToolResult.error_result(f"Injury report lookup failed: {e}")

    async def _get_injury_report(self, team: str, sport: str) -> str:
        """Fetch current injury data via web search."""
        from ite.tools.builtin.web_search import WebSearchTool

        search_tool = WebSearchTool(self.config)

        sport_hint = f" {sport}" if sport else ""
        query = f"{team}{sport_hint} injury report today current injuries"
        search_result = await search_tool.execute(
            ToolInvocation(
                params={"query": query, "max_results": 4},
                cwd=self.config.cwd,
            )
        )

        output_lines = [
            f"## Injury Report: {team}{sport_hint}",
            "",
        ]

        if search_result.success:
            output_lines.append(search_result.output[:3500])
            output_lines.append("")
            output_lines.append("---")
            output_lines.append(
                "**Betting impact:** Key players out can shift spreads 3-7 points in NBA, "
                "2-3 points in NFL. Always cross-reference with the opponent's injury report "
                "before finalizing any bet."
            )
        else:
            output_lines.append(f"_Lookup failed: {search_result.error}_")

        return "\n".join(output_lines)
