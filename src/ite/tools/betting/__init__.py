"""Betting-specific tools for sports prediction agents.

Each tool follows the standard iTE Tool protocol (name, description,
kind, Pydantic schema, async execute). They are registered alongside
the agent when the `betting` preset is active.
"""

from __future__ import annotations

from ite.tools.betting.fetch_odds import FetchOddsTool
from ite.tools.betting.head_to_head import HeadToHeadTool
from ite.tools.betting.injury_report import InjuryReportTool
from ite.tools.betting.model_prediction import ModelPredictionTool

__all__ = [
    "FetchOddsTool",
    "HeadToHeadTool",
    "InjuryReportTool",
    "ModelPredictionTool",
]


def get_betting_tools() -> list[type]:
    """Return all betting-specific tool classes."""
    return [
        FetchOddsTool,
        HeadToHeadTool,
        InjuryReportTool,
        ModelPredictionTool,
    ]
