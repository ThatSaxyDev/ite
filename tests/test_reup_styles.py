from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ite.ui.reup.app import ReupApp


class WorkboardStyleApp(App[None]):
    CSS_PATH: ClassVar[list[Path]] = [
        Path(__file__).parents[1] / "src/ite/ui/reup" / path
        for path in ReupApp.CSS_PATH
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="workboard", classes="block workboard"):
            yield Static("Workboard", classes="card-title")
            yield Static("Body", classes="card-body")


def test_workboard_card_preserves_the_current_layout() -> None:
    async def run() -> None:
        app = WorkboardStyleApp()
        async with app.run_test():
            workboard = app.query_one("#workboard", Vertical)
            title = workboard.query_one(".card-title", Static)
            body = workboard.query_one(".card-body", Static)

            assert workboard.styles.border.top[0] == "round"
            assert workboard.styles.margin.top == 1
            assert workboard.styles.margin.right == 2
            assert workboard.styles.margin.bottom == 2
            assert workboard.styles.margin.left == 0
            assert title.styles.margin.bottom == 1
            assert body.styles.margin.top == 0
            assert body.styles.padding == (0, 0, 0, 0)

    asyncio.run(run())
