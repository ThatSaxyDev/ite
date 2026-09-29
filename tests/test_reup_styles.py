from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ite.ui.reup.app import ReupApp
from ite.ui.reup.settings import AppFooter, FooterLink


class WorkboardStyleApp(App[None]):
    CSS_PATH: ClassVar[list[Path]] = [
        Path(__file__).parents[1] / "src/ite/ui/reup" / path
        for path in ReupApp.CSS_PATH
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="workboard", classes="block workboard"):
            yield Static("Workboard", classes="card-title")
            yield Static("Body", classes="card-body")


class SignedOutFooterStyleApp(App[None]):
    CSS_PATH: ClassVar[list[Path]] = [
        Path(__file__).parents[1] / "src/ite/ui/reup" / path
        for path in ReupApp.CSS_PATH
    ]

    def compose(self) -> ComposeResult:
        yield AppFooter(id="signed-out-footer", classes="signed-out-footer")


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


def test_signed_out_screen_requires_sign_in() -> None:
    source = (
        Path(__file__).parents[1] / "src/ite/ui/reup/app.py"
    ).read_text(encoding="utf-8")

    assert 'id="cloud-sign-in"' in source
    assert 'id="cloud-exit"' in source
    assert 'id="signed-out-footer"' in source
    assert 'id="cloud-skip-sign-in"' not in source


def test_signed_out_footer_uses_the_shared_credit_component() -> None:
    async def run() -> None:
        app = SignedOutFooterStyleApp()
        async with app.run_test():
            footer = app.query_one("#signed-out-footer", AppFooter)
            links = list(footer.query(FooterLink))

            assert footer.styles.dock == "bottom"
            assert [link.url for link in links] == [
                "https://kiishi.space",
                "https://github.com/ThatSaxyDev/ite",
                "https://www.linkedin.com/in/david-dedeke-382915281",
                "https://x.com/itetheagent",
            ]

    asyncio.run(run())
