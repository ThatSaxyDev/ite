from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.widget import Widget

from ite.runtime.state import SessionRunState

__all__ = ["SessionRunState", "ShellSessionCardState"]


@dataclass
class ShellSessionCardState:
    card: Widget
    name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any]
    payload: str
    success: bool
    exit_code: int | None
