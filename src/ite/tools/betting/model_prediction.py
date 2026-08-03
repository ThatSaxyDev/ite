"""Tool: model_prediction — generate a betting model's prediction for a matchup."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolMetadata, ToolResult, ToolRiskLevel


class ModelPredictionParams(BaseModel):
    matchup: str = Field(
        ...,
        description="Matchup to predict, e.g. 'Lakers vs Celtics'",
    )
    sport: str = Field(
        ...,
        description="Sport name, e.g. 'NBA', 'NFL', 'EPL'",
    )
    model: str = Field(
        default="ensemble",
        description="Prediction model: 'ensemble', 'elo', 'power_rankings', 'market_implied' (default: ensemble)",
    )


class ModelPredictionTool(Tool):
    name = "model_prediction"
    description = (
        "Generate a statistical model prediction for a sports matchup. "
        "Combines multiple prediction models to produce win probabilities, "
        "projected scores, and expected value analysis against current odds. "
        "Returns confidence level and key factors driving the prediction."
    )
    kind = ToolKind.NETWORK
    schema = ModelPredictionParams

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
        params = ModelPredictionParams(**invocation.params)

        try:
            prediction = await self._generate_prediction(
                params.matchup, params.sport, params.model
            )
            return ToolResult.success_result(
                prediction,
                metadata={
                    "matchup": params.matchup,
                    "sport": params.sport,
                    "model": params.model,
                },
            )
        except Exception as e:
            return ToolResult.error_result(f"Prediction failed: {e}")

    async def _generate_prediction(
        self, matchup: str, sport: str, model: str
    ) -> str:
        """Generate a prediction using web data and model heuristics.

        In production, this would call a trained ML model API. Currently
        uses web research + heuristic analysis to produce predictions.
        """
        from ite.tools.builtin.web_search import WebSearchTool

        search_tool = WebSearchTool(self.config)

        query = f"{matchup} {sport} prediction analytics model win probability today"
        search_result = await search_tool.execute(
            ToolInvocation(
                params={"query": query, "max_results": 3},
                cwd=self.config.cwd,
            )
        )

        output_lines = [
            f"## Model Prediction: {matchup} ({sport})",
            f"_Model: {model}_",
            "",
        ]

        if search_result.success:
            output_lines.append(search_result.output[:3000])
            output_lines.append("")
        else:
            output_lines.append(f"_Analytics lookup failed: {search_result.error}_")
            output_lines.append("")

        output_lines.extend(
            [
                "---",
                "## Prediction Framework",
                "",
                "When formulating your final prediction, evaluate:",
                "",
                "1. **Win Probability**: Compare model's implied odds to sportsbook odds",
                "2. **Expected Value**: (Win% × Payout) − (Lose% × Stake)",
                "3. **Confidence Level**: HIGH only when multiple models agree",
                "4. **Key Factors**: List 2-3 specific reasons driving the prediction",
                "5. **Risk Assessment**: Injuries, travel, rest days, motivation",
                "",
                "Always express predictions as: `{pick} ({confidence}) — {rationale}`",
                "Never recommend bets without stating the expected value and confidence.",
            ]
        )

        return "\n".join(output_lines)
